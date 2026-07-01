"""Append-only trade journal — JSON lines + summary CSV."""

import json, os, csv
from datetime import datetime, timezone
import config

_JOURNAL = os.path.join(config.LOG_DIR, 'trades.jsonl')
_SUMMARY = os.path.join(config.LOG_DIR, 'trades_summary.csv')

_CSV_FIELDS = [
    'date', 'instrument', 'direction', 'entry_price', 'tp1_price', 'tp2_price',
    'sl_initial', 'close_price', 'close_reason',
    'leg1_pnl_pips', 'leg2_pnl_pips', 'total_pnl_pips', 'entry_range_pips',
]


def _now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')


def _append_jsonl(record: dict):
    os.makedirs(config.LOG_DIR, exist_ok=True)
    with open(_JOURNAL, 'a') as f:
        f.write(json.dumps(record, default=str) + '\n')


def log_event(event: str, **kwargs):
    _append_jsonl({'time': _now(), 'event': event, **kwargs})
    print(f'[{_now()}] {event}', ' | '.join(f'{k}={v}' for k, v in kwargs.items()))


def log_trade_close(state: dict, instrument: str, close_price: float,
                    close_reason: str, leg1_pnl_pips: float, leg2_pnl_pips: float,
                    units_leg1: int, units_leg2: int):
    # Size-weighted position P&L. leg*_pnl_pips are per-unit price moves; each leg
    # is only part of the position, so the position result is the size-weighted
    # blend — NOT leg1 + leg2. Summing double-counted (both legs on an SL-only exit
    # move the same distance → reported 2× the real loss, e.g. Trade 5 −86.4 vs the
    # true −43.2). The weighted figure reconciles with dollar/NAV. Fixed v1.7.1.
    total_units = units_leg1 + units_leg2
    total = (leg1_pnl_pips * units_leg1 + leg2_pnl_pips * units_leg2) / total_units
    record = {
        'date':             _now(),
        'instrument':       instrument,
        'direction':        state['direction'],
        'entry_price':      state['entry_price'],
        'tp1_price':        state['tp1'],
        'tp2_price':        state['tp2'],
        'sl_initial':       state['sl_initial'],
        'close_price':      close_price,
        'close_reason':     close_reason,
        'leg1_pnl_pips':    round(leg1_pnl_pips, 1),
        'leg2_pnl_pips':    round(leg2_pnl_pips, 1),
        'total_pnl_pips':   round(total, 1),
        'entry_range_pips': state.get('entry_range'),
    }
    _append_jsonl({'event': 'trade_close', **record})

    os.makedirs(config.LOG_DIR, exist_ok=True)
    write_header = not os.path.exists(_SUMMARY)
    with open(_SUMMARY, 'a', newline='') as f:
        w = csv.DictWriter(f, fieldnames=_CSV_FIELDS)
        if write_header:
            w.writeheader()
        w.writerow(record)

    return total
