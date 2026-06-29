"""Single-position state for the EUR/GBP pairs bot. File: logs/pairs_state.json."""
import json, os
from config import LOG_DIR

_STATE_FILE = os.path.join(LOG_DIR, 'pairs_state.json')

_EMPTY = {
    'status':          'flat',     # flat | in_position
    'trade_id':        None,
    'direction':       None,       # short | long
    'entry_price':     None,
    'units':           None,
    'stop_price':      None,
    'entry_z':         None,
    'signal_date':     None,       # date of the daily bar that triggered entry
    'fill_time':       None,
    'last_daily_date': None,       # most recent completed daily bar we've acted on
}


def load() -> dict:
    os.makedirs(LOG_DIR, exist_ok=True)
    if not os.path.exists(_STATE_FILE):
        return dict(_EMPTY)
    with open(_STATE_FILE) as f:
        saved = json.load(f)
    return {**_EMPTY, **saved}


def save(state: dict):
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(_STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2, default=str)


def reset(state: dict) -> dict:
    """Clear the position but PRESERVE last_daily_date (so we don't re-trade the
    same bar after an exit)."""
    last = state.get('last_daily_date')
    state.clear()
    state.update(_EMPTY)
    state['last_daily_date'] = last
    save(state)
    return state
