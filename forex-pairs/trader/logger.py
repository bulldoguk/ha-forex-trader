"""Append-only journal for the pairs bot — JSON lines + a trade summary CSV."""
import json, os, csv
from datetime import datetime, timezone
import config

_JOURNAL = os.path.join(config.LOG_DIR, 'pairs_trades.jsonl')
_SUMMARY = os.path.join(config.LOG_DIR, 'pairs_trades_summary.csv')

_CSV_FIELDS = ['close_time', 'instrument', 'direction', 'entry_price', 'close_price',
               'close_reason', 'entry_z', 'units', 'realized_pl', 'pnl_pips',
               'signal_date', 'fill_time']


def _now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')


def _append(record: dict):
    os.makedirs(config.LOG_DIR, exist_ok=True)
    with open(_JOURNAL, 'a') as f:
        f.write(json.dumps(record, default=str) + '\n')


def log_event(event: str, **kwargs):
    _append({'time': _now(), 'event': event, **kwargs})
    print(f'[{_now()}] {event} ' + ' | '.join(f'{k}={v}' for k, v in kwargs.items()),
          flush=True)


def log_trade_close(state: dict, close_price: float, close_reason: str,
                    realized_pl: float, pnl_pips: float):
    record = {
        'close_time':   _now(),
        'instrument':   config.INSTRUMENT,
        'direction':    state.get('direction'),
        'entry_price':  state.get('entry_price'),
        'close_price':  close_price,
        'close_reason': close_reason,
        'entry_z':      state.get('entry_z'),
        'units':        state.get('units'),
        'realized_pl':  round(realized_pl, 2),
        'pnl_pips':     round(pnl_pips, 1),
        'signal_date':  state.get('signal_date'),
        'fill_time':    state.get('fill_time'),
    }
    _append({'event': 'trade_close', **record})
    os.makedirs(config.LOG_DIR, exist_ok=True)
    write_header = not os.path.exists(_SUMMARY)
    with open(_SUMMARY, 'a', newline='') as f:
        w = csv.DictWriter(f, fieldnames=_CSV_FIELDS)
        if write_header:
            w.writeheader()
        w.writerow(record)
