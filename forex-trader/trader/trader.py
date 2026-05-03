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
    sig = scanner.latest_signal(key)
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


# ── Main loop ─────────────────────────────────────────────────────────────────

def run():
    print(f'[{datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}] '
          f'Trader daemon starting — instruments: {", ".join(config.INSTRUMENTS)}')

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

    while True:
        try:
            # ── Monitor all filled positions (runs continuously) ──────────────
            any_filled = any(state[k]['status'] == 'filled'
                             for k in config.INSTRUMENTS)
            if any_filled:
                for key in config.INSTRUMENTS:
                    if state[key]['status'] == 'filled':
                        state = _handle_filled(state, key)
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
