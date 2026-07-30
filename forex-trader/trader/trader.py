#!/usr/bin/env python3
"""
Multi-instrument Automated Trader Daemon
=========================================
Instruments: GBP/USD, EUR/USD, Gold (XAU/USD)

On each M15 close:
  - Scans every idle instrument for a signal; places limit order if found
  - Checks pending instruments for fills or TTL expiry
  - Monitors all filled positions for TP1/TP2/SL

Each instrument is managed independently with its own pivot set and state.

Usage:
  python3 trader.py           # run daemon
  python3 trader.py --status  # show all instrument states and exit
  python3 trader.py --reset   # clear all state (use after manual intervention)
"""

import sys, os, time, traceback, warnings
from datetime import datetime, timezone, timedelta

warnings.filterwarnings('ignore', message='urllib3 v2 only supports OpenSSL')

import config
import oanda_client
import scanner
import monitor
import notifier
import logger
import state as _state
import mqtt_publisher


def _next_m15_close() -> datetime:
    now    = datetime.now(timezone.utc)
    minute = (now.minute // 15 + 1) * 15
    if minute == 60:
        return now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return now.replace(minute=minute, second=0, microsecond=0)


def _sleep_until(dt: datetime):
    secs = (dt - datetime.now(timezone.utc)).total_seconds()
    if secs > 0:
        time.sleep(secs)


# ── Per-instrument handlers ───────────────────────────────────────────────────

def _handle_idle(state: dict, key: str) -> dict:
    active = sum(1 for k in config.INSTRUMENTS if state[k]['status'] != 'idle')
    if active >= config.MAX_CONCURRENT_POSITIONS:
        return state

    try:
        sig = scanner.latest_signal(key)
    except Exception:
        logger.log_event('scan_error', instrument=key, detail=traceback.format_exc())
        return state
    if sig is None:
        return state

    instr_cfg    = config.INSTRUMENTS[key]
    entry_range  = scanner.pips(
        sig.entry_price - sig.p if sig.direction == 'short' else sig.p - sig.entry_price,
        key,
    )
    logger.log_event('signal_found', instrument=key, direction=sig.direction,
                     entry=sig.entry_price, tp1=sig.tp1, tp2=sig.tp2,
                     sl=sig.sl_initial, range=entry_range)

    # Margin pre-check. OANDA only validates margin at FILL time, so without this
    # an unaffordable order sits pending and is then cancelled by the broker —
    # which the daemon used to mis-report as "price moved away / TTL expired"
    # (that is how txn 82 stayed invisible). Checking up front turns a silent
    # rejection into a logged, countable deferral. The signal is not lost: the
    # instrument stays idle and re-scans on the next M15 close.
    ok, required, available = oanda_client.check_margin(
        instr_cfg['oanda'], instr_cfg['units_total'])
    if not ok:
        logger.log_event('signal_deferred_margin', instrument=key,
                         direction=sig.direction, entry=sig.entry_price,
                         margin_required=round(required, 2),
                         margin_available=round(available, 2),
                         safety_factor=config.MARGIN_SAFETY_FACTOR)
        return state

    try:
        resp = oanda_client.place_limit_order(
            sig.direction, sig.entry_price,
            instr_cfg['units_total'], sig.sl_initial,
            instrument=instr_cfg['oanda'],
        )
    except Exception:
        logger.log_event('order_error', instrument=key, detail=traceback.format_exc())
        notifier.error(f'place_limit_order ({key})', traceback.format_exc())
        return state

    order_id = (resp.get('orderCreateTransaction', {}).get('id') or
                resp.get('relatedTransactionIDs', ['?'])[0])

    state[key].update({
        'status':            'pending',
        'order_id':          order_id,
        'direction':         sig.direction,
        'entry_price':       sig.entry_price,
        'sl_initial':        sig.sl_initial,
        'sl_current':        sig.sl_initial,
        'sl_after_tp1':      sig.sl_after_tp1,
        'tp1':               sig.tp1,
        'tp2':               sig.tp2,
        'entry_range':       entry_range,
        'signal_time':       str(datetime.now(timezone.utc)),
        'bars_since_signal': 0,
    })
    _state.save(state)

    notifier.signal_detected(key, sig.direction, sig.entry_price,
                             sig.tp1, sig.tp2, sig.sl_initial, entry_range)
    return state


def _resolve_vanished_order(state: dict, key: str) -> dict:
    """
    The order is no longer pending and no position is open. Two very different
    causes, which the daemon used to conflate as "price moved away / TTL expired":

      FILLED    — it filled AND closed inside a single scan gap (a fast SL or TP).
                  The trade is real and must be journaled, or it silently vanishes
                  from the track record — the class of gap behind the 2026-07-16
                  missing-trades reconciliation. Seen live on 2026-07-30: order 154
                  filled at 10:46:00 and stopped out at 10:49:47, between two scans.
      CANCELLED — the broker rejected or expired it. INSUFFICIENT_MARGIN is the one
                  we have actually seen (txn 82, 2026-07-01).

    On any lookup failure we leave the state untouched so the TTL path can still
    resolve it — guessing here would risk inventing or losing a trade.
    """
    st = state[key]
    try:
        order = oanda_client.get_order(st['order_id'])
    except Exception:
        logger.log_event('order_state_lookup_failed', instrument=key,
                         order_id=st['order_id'], detail=traceback.format_exc())
        return state

    order_state = order.get('state')

    if order_state == 'CANCELLED':
        logger.log_event('order_rejected_by_broker', instrument=key,
                         order_id=st['order_id'],
                         detail=order.get('cancellingTransactionID', 'no reason given'))
        notifier.order_cancelled(
            key, 'Order cancelled by the broker before filling — check free margin')
        _state.reset_instrument(state, key)
        return state

    if order_state != 'FILLED':
        return state   # PENDING/TRIGGERED — let the normal paths handle it

    # Filled. Recover the real fill price, then settle from the trade record.
    trade_id = order.get('tradeOpenedID')
    if not trade_id:
        return state
    try:
        trade = oanda_client.get_trade(trade_id)
    except Exception:
        logger.log_event('order_state_lookup_failed', instrument=key,
                         order_id=st['order_id'], detail=traceback.format_exc())
        return state

    st['trade_id']    = trade_id
    st['entry_price'] = float(trade.get('price', st['entry_price']))
    st['fill_time']   = trade.get('openTime', str(datetime.now(timezone.utc)))

    if trade.get('state') != 'CLOSED':
        # Filled and still open — we simply missed the fill event. Adopt it.
        st['status'] = 'filled'
        _state.save(state)
        logger.log_event('order_filled', instrument=key, trade_id=trade_id,
                         fill_price=st['entry_price'],
                         detail='fill detected late via order state')
        return state

    # Filled AND already closed inside the scan gap — journal it retroactively.
    close_price = float(trade.get('averageClosePrice', st['entry_price']))
    realized    = float(trade.get('realizedPL', 0.0))
    st['status'] = 'filled'
    logger.log_event('missed_fill_and_close', instrument=key, trade_id=trade_id,
                     entry=st['entry_price'], close=close_price,
                     realized_pl=realized,
                     detail='opened and closed between scans — journaled retroactively')
    monitor.settle_closed_trade(st, close_price, 'sl_or_fast_exit', key)
    _state.reset_instrument(state, key)
    return state


def _handle_pending(state: dict, key: str) -> dict:
    st = state[key]
    st['bars_since_signal'] = st.get('bars_since_signal', 0) + 1

    oanda_instr = config.INSTRUMENTS[key]['oanda']
    try:
        open_trades = oanda_client.get_open_trades(instrument=oanda_instr)
    except Exception:
        return state

    if open_trades:
        trade     = open_trades[0]
        trade_id  = trade['id']
        fill_price = float(trade.get('price', st['entry_price']))

        st.update({'status': 'filled', 'trade_id': trade_id,
                   'fill_time': str(datetime.now(timezone.utc))})
        _state.save(state)

        logger.log_event('order_filled', instrument=key,
                         trade_id=trade_id, fill_price=fill_price)
        notifier.order_filled(key, st['direction'], fill_price,
                              config.INSTRUMENTS[key]['units_total'],
                              st['sl_initial'], st['tp1'], st['tp2'])
        return state

    # The order vanished at the broker without opening a trade → OANDA cancelled it
    # (INSUFFICIENT_MARGIN is the one we've actually seen — txn 82 on 2026-07-01).
    # Previously this fell through to the TTL branch below and was reported as
    # "price moved away", hiding a margin problem as ordinary non-fill.
    try:
        pending_ids = {o['id'] for o in
                       oanda_client.get_pending_orders(instrument=oanda_instr)}
    except Exception:
        pending_ids = None

    if pending_ids is not None and st['order_id'] not in pending_ids:
        return _resolve_vanished_order(state, key)

    if st['bars_since_signal'] >= config.LIMIT_ORDER_TTL:
        try:
            oanda_client.cancel_order(st['order_id'])
        except Exception:
            pass
        logger.log_event('order_cancelled', instrument=key, reason='TTL expired')
        notifier.order_cancelled(key, 'Price moved away — limit TTL expired')
        _state.reset_instrument(state, key)

    return state


def _handle_filled(state: dict, key: str) -> dict:
    event, updated_st = monitor.check_and_act(state[key], key)
    if event == 'closed':
        _state.reset_instrument(state, key)
    else:
        if updated_st:
            state[key] = updated_st
        _state.save(state)
    return state


def _check_connection_health() -> None:
    """Watchdog: alert + flag MQTT when OANDA calls are failing repeatedly.

    Runs once per loop iteration. The per-instrument handlers deliberately swallow
    OANDA exceptions to stay resilient, so without this a revoked token or network
    outage fails silently (as it did 2026-07-15: the GBP/USD position went
    unmanaged ~17h with no alert). notifier.error's 1h per-context cooldown keeps
    this to a single email per hour while degraded.
    """
    h = oanda_client.get_health()
    degraded = h['consecutive_failures'] >= config.CONN_FAILURE_ALERT_THRESHOLD
    mqtt_publisher.publish_connection(not degraded, h)
    if not degraded:
        return

    is_auth = h['last_status'] in (401, 403)
    context = 'oanda_auth' if is_auth else 'oanda_connection'
    hint = (
        "The OANDA API token is being rejected (401/403) — it has most likely been "
        "revoked or the practice account was reset. Fix: update the add-on's "
        "oanda_token option and restart the add-on."
        if is_auth else
        "OANDA is unreachable or returning errors. Check network / OANDA status — "
        "the daemon keeps retrying and will recover on its own once calls succeed."
    )
    detail = (
        f"{h['consecutive_failures']} consecutive OANDA call failures — the daemon "
        f"cannot see prices or manage open positions.\n\n"
        f"Last HTTP status:      {h['last_status']}\n"
        f"Last error:            {h['last_error']}\n"
        f"Last successful call:  {h['last_success']}\n\n"
        f"{hint}"
    )
    notifier.error(context, detail)


# ── Main loop ─────────────────────────────────────────────────────────────────

def run():
    print(f'[{datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}] '
          f'Trader daemon starting — instruments: {", ".join(config.INSTRUMENTS)}  '
          f'monitor.VERSION={monitor.VERSION}')

    try:
        acct = oanda_client.get_account_summary()
        print(f'  OANDA connected — balance: {acct["balance"]}, NAV: {acct["NAV"]}')
    except Exception:
        print('  ERROR: Could not connect to OANDA.')
        notifier.error('startup', traceback.format_exc())
        sys.exit(1)

    state = _state.load()
    for key, st in state.items():
        print(f'  {key}: {st["status"]}')
    logger.log_event('daemon_start',
                     instruments=list(config.INSTRUMENTS.keys()),
                     statuses={k: state[k]['status'] for k in state})

    mqtt_publisher.publish_account(acct)
    mqtt_publisher.publish_status(state)
    mqtt_publisher.publish_connection(True, oanda_client.get_health())
    notifier.startup(list(config.INSTRUMENTS.keys()))

    while True:
        try:
            # ── Monitor all filled positions (runs continuously) ──────────────
            any_filled = any(state[k]['status'] == 'filled'
                             for k in config.INSTRUMENTS)
            if any_filled:
                for key in config.INSTRUMENTS:
                    if state[key]['status'] == 'filled':
                        state = _handle_filled(state, key)
                try:
                    acct = oanda_client.get_account_summary()
                    mqtt_publisher.publish_account(acct)
                except Exception:
                    pass
                mqtt_publisher.publish_status(state)
                _check_connection_health()
                time.sleep(config.MONITOR_INTERVAL)
                continue

            # ── Wait for next M15 close, then scan ───────────────────────────
            next_close = _next_m15_close()
            wait_until = next_close + timedelta(seconds=config.SCAN_DELAY_SECS)
            statuses   = {k: state[k]['status'] for k in config.INSTRUMENTS}
            print(f'  [{datetime.now(timezone.utc):%H:%M:%S UTC}] '
                  f'Sleeping until {wait_until:%H:%M:%S UTC}  |  '
                  + '  '.join(f'{k}:{v}' for k, v in statuses.items()),
                  flush=True)
            _sleep_until(wait_until)

            # ── Scan all instruments ──────────────────────────────────────────
            now_str = datetime.now(timezone.utc).strftime('%H:%M:%S UTC')
            print(f'  [{now_str}] Scanning...', flush=True)
            for key in config.INSTRUMENTS:
                st_key = state[key]['status']
                if st_key == 'idle':
                    state = _handle_idle(state, key)
                elif st_key == 'pending':
                    state = _handle_pending(state, key)
            print(f'  [{now_str}] Scan complete — '
                  + '  '.join(f'{k}:{state[k]["status"]}' for k in config.INSTRUMENTS),
                  flush=True)
            logger.log_event('scan_complete',
                             statuses={k: state[k]['status'] for k in state})

            try:
                acct = oanda_client.get_account_summary()
                mqtt_publisher.publish_account(acct)
            except Exception:
                pass
            mqtt_publisher.publish_status(state)
            _check_connection_health()

        except KeyboardInterrupt:
            print('\nDaemon stopped.')
            logger.log_event('daemon_stop', reason='keyboard_interrupt')
            break
        except Exception:
            detail = traceback.format_exc()
            logger.log_event('daemon_error', detail=detail)
            notifier.error('daemon_loop', detail)
            time.sleep(60)


def show_status():
    state = _state.load()
    for key, st in state.items():
        print(f'\n{key} — {st["status"].upper()}')
        for k, v in st.items():
            if v is not None and k != 'status':
                print(f'  {k:<22} {v}')


if __name__ == '__main__':
    if '--status' in sys.argv:
        show_status()
    elif '--reset' in sys.argv:
        _state.reset_all()
        print('All instrument states reset to idle.')
    else:
        run()
