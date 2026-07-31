"""
Persists daemon state for all active instruments.
State file: logs/trader_state.json
"""

import json, os
from config import LOG_DIR, INSTRUMENTS

_STATE_FILE = os.path.join(LOG_DIR, 'trader_state.json')

_EMPTY_INSTRUMENT = {
    'status':            'idle',   # idle | pending | filled
    'order_id':          None,
    'trade_id':          None,
    'direction':         None,
    'entry_price':       None,
    'sl_initial':        None,
    'sl_current':        None,
    'sl_after_tp1':      None,
    'tp1':               None,
    'tp2':               None,
    'entry_range':       None,
    'signal_time':       None,
    'fill_time':         None,
    'tp1_hit':           False,
    'tp1_realized_pl':   None,   # $ realized on the TP1 partial (dashboard "Locked P&L")
    'leg1_pips':         None,   # pips gained on the TP1 leg
    'tp1_price_actual':  None,   # price the TP1 partial actually executed at — needed
                                 # to back the runner's exit out of averageClosePrice
    'bars_since_signal': 0,
}


def _empty_state() -> dict:
    return {key: dict(_EMPTY_INSTRUMENT) for key in INSTRUMENTS}


def load() -> dict:
    os.makedirs(LOG_DIR, exist_ok=True)
    if not os.path.exists(_STATE_FILE):
        return _empty_state()
    with open(_STATE_FILE) as f:
        saved = json.load(f)
    # Add any new instruments not yet in saved state
    state = _empty_state()
    for key in INSTRUMENTS:
        if key in saved:
            state[key] = saved[key]
    return state


def save(state: dict):
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(_STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2, default=str)


def reset_instrument(state: dict, key: str) -> dict:
    state[key] = dict(_EMPTY_INSTRUMENT)
    save(state)
    return state


def reset_all() -> dict:
    s = _empty_state()
    save(s)
    return s
