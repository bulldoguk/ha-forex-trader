#!/usr/bin/env python3
"""
EUR/GBP pairs-reversion daemon.

Daily cadence: a trading decision fires only when a new COMPLETED daily candle
appears. Between daily bars the bot wakes hourly to reconcile with the broker
(detect a stop-out promptly) and refresh Home Assistant sensors. Single position
at a time; the MR bot's trades on the same account are ignored (instrument-filtered).

Usage:
  python3 pairs_trader.py            # run daemon
  python3 pairs_trader.py --status   # print state and exit
  python3 pairs_trader.py --reset    # clear local state (after manual intervention)
"""
import sys, time, traceback
from datetime import datetime, timezone

import config
import oanda_client as oa
import pairs_strategy as ps
import state as _state
import notifier
import logger
import mqtt_publisher as mqtt

VERSION = '0.3.0'


def _pips(entry: float, close: float, direction: str) -> float:
    delta = (entry - close) if direction == 'short' else (close - entry)
    return delta / config.PIP_SIZE


def _latest_closes():
    df = oa.get_candles(config.INSTRUMENT, 'D', config.DAILY_LOOKBACK)
    return df['close']


# ── Broker reconciliation ─────────────────────────────────────────────────────

def reconcile(state: dict) -> dict:
    """If we think we hold a position but the broker no longer shows it, the SL
    fired (or it was closed manually). Settle it from the trade record."""
    if state['status'] != 'in_position' or not state['trade_id']:
        return state
    open_ids = {t['id'] for t in oa.get_open_trades(config.INSTRUMENT)}
    if state['trade_id'] in open_ids:
        return state  # still open, nothing to do

    try:
        tr = oa.get_trade(state['trade_id'])
        close_px = float(tr.get('averageClosePrice', state['entry_price']))
        realized = float(tr.get('realizedPL', 0.0))
    except Exception:
        close_px, realized = state['entry_price'], 0.0
    pnl_pips = _pips(state['entry_price'], close_px, state['direction'])
    logger.log_trade_close(state, close_px, 'stop_or_manual', realized, pnl_pips)
    notifier.exited(state['direction'], state['entry_price'], close_px,
                    'stop_or_manual', realized, pnl_pips)
    logger.log_event('position_closed_by_broker', trade_id=state['trade_id'],
                     close=close_px, realized_pl=realized, pips=round(pnl_pips, 1))
    return _state.reset(state)


# ── Daily decision ────────────────────────────────────────────────────────────

def act_on_new_bar(state: dict, closes) -> dict:
    in_pos = state['status'] == 'in_position'
    d = ps.decide(closes, in_position=in_pos, direction=state.get('direction'))
    bar_date = closes.index[-1].date().isoformat()

    logger.log_event('daily_decision', bar=bar_date, z=round(d['z'], 2),
                     action=d['action'], reason=d['reason'],
                     mode='DRY_RUN' if config.DRY_RUN else 'LIVE')

    if d['action'] == 'enter':
        if config.DRY_RUN:
            logger.log_event('dry_run_would_enter', direction=d['direction'],
                             z=round(d['z'], 2), stop=round(d['stop'], 5))
        else:
            state = _open_position(state, d)
    elif d['action'] == 'exit':
        if config.DRY_RUN:
            logger.log_event('dry_run_would_exit', reason=d['reason'])
        else:
            state = _close_position(state, d['reason'])

    state['last_daily_date'] = bar_date
    _state.save(state)
    return state


def _open_position(state: dict, d: dict) -> dict:
    # Margin pre-check on the shared account. Without it an unaffordable entry is
    # rejected by OANDA (txn 129) and surfaces only as an error email; with it the
    # skip is logged as a countable deferral. The signal is deferred, not lost —
    # the next daily bar re-decides and re-enters while |z| still qualifies, which
    # is exactly how the 07-16 block became the 07-20 fill.
    ok, required, available = oa.check_margin(config.INSTRUMENT, config.UNITS)
    if not ok:
        logger.log_event('signal_deferred_margin', direction=d['direction'],
                         z=round(d['z'], 2),
                         margin_required=round(required, 2),
                         margin_available=round(available, 2),
                         safety_factor=config.MARGIN_SAFETY_FACTOR)
        return state

    resp = oa.place_market_order(d['direction'], config.UNITS, d['stop'], config.INSTRUMENT)
    fill = resp.get('orderFillTransaction')
    if not fill or 'tradeOpened' not in fill:
        logger.log_event('order_not_filled', detail=str(resp)[:300])
        notifier.error('place_market_order', f'no fill: {str(resp)[:300]}')
        return state
    trade_id  = fill['tradeOpened']['tradeID']
    fill_price = float(fill['price'])
    state.update(status='in_position', trade_id=trade_id, direction=d['direction'],
                 entry_price=fill_price, units=config.UNITS, stop_price=d['stop'],
                 entry_z=round(d['z'], 2),
                 signal_date=d.get('bar') or state.get('last_daily_date'),
                 fill_time=str(datetime.now(timezone.utc)))
    logger.log_event('position_opened', trade_id=trade_id, direction=d['direction'],
                     entry=fill_price, stop=round(d['stop'], 5), z=round(d['z'], 2))
    notifier.entered(d['direction'], fill_price, config.UNITS, d['stop'], d['z'])
    return state


def _close_position(state: dict, reason: str) -> dict:
    try:
        oa.close_trade(state['trade_id'])
        tr = oa.get_trade(state['trade_id'])
        close_px = float(tr.get('averageClosePrice', state['entry_price']))
        realized = float(tr.get('realizedPL', 0.0))
    except Exception:
        logger.log_event('close_error', detail=traceback.format_exc())
        notifier.error('close_trade', traceback.format_exc())
        return state
    pnl_pips = _pips(state['entry_price'], close_px, state['direction'])
    logger.log_trade_close(state, close_px, reason, realized, pnl_pips)
    notifier.exited(state['direction'], state['entry_price'], close_px,
                    reason, realized, pnl_pips)
    logger.log_event('position_closed', trade_id=state['trade_id'], close=close_px,
                     realized_pl=realized, pips=round(pnl_pips, 1))
    return _state.reset(state)


# ── Main loop ─────────────────────────────────────────────────────────────────

def _sleep_to_next_cycle() -> None:
    """
    Sleep until the next CHECK_INTERVAL boundary offset by CHECK_OFFSET_MINS.

    Aligned to the wall clock rather than sleeping a flat interval: a plain
    time.sleep(3600) lets the wake time drift with each loop's own duration, so
    the bot cannot be held clear of the MR bot's quarter-hour scans. Anchoring to
    the boundary keeps it in a fixed slot indefinitely.
    """
    now      = datetime.now(timezone.utc).timestamp()
    interval = config.CHECK_INTERVAL_SECS
    offset   = config.CHECK_OFFSET_MINS * 60
    next_run = ((now - offset) // interval + 1) * interval + offset
    time.sleep(max(1.0, next_run - now))



def run():
    print(f'[{datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}] Pairs daemon '
          f'starting — {config.INSTRUMENT}  VERSION={VERSION}  '
          f'{"DRY_RUN" if config.DRY_RUN else "LIVE"}  units={config.UNITS}', flush=True)
    try:
        acct = oa.get_account_summary()
        print(f'  OANDA connected — balance {acct["balance"]}, NAV {acct["NAV"]}', flush=True)
    except Exception:
        print('  ERROR: cannot connect to OANDA', flush=True)
        notifier.error('startup', traceback.format_exc())
        sys.exit(1)

    state = _state.load()
    print(f'  state: {state["status"]}  last_bar={state["last_daily_date"]}', flush=True)
    notifier.startup(config.DRY_RUN, config.UNITS)

    while True:
        try:
            state = reconcile(state)
            closes = _latest_closes()
            bar_date = closes.index[-1].date().isoformat()
            if bar_date != state['last_daily_date']:
                state = act_on_new_bar(state, closes)
            else:
                z, _, _ = ps.compute_z(closes)
                logger.log_event('idle_check', bar=bar_date, z=round(z, 2),
                                 status=state['status'])
            try:
                z_now, _, _ = ps.compute_z(closes)
                mqtt.publish_status(state, z_now)
                mqtt.publish_account(oa.get_account_summary())
            except Exception:
                pass
        except KeyboardInterrupt:
            print('\nDaemon stopped.', flush=True)
            break
        except Exception:
            logger.log_event('daemon_error', detail=traceback.format_exc())
            notifier.error('daemon_loop', traceback.format_exc())
        _sleep_to_next_cycle()


def show_status():
    s = _state.load()
    for k, v in s.items():
        print(f'  {k:<18} {v}')


if __name__ == '__main__':
    if '--status' in sys.argv:
        show_status()
    elif '--reset' in sys.argv:
        _state.reset(_state.load())
        print('Pairs state reset to flat.')
    else:
        run()
