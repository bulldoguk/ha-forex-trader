"""OANDA v20 REST wrapper for the pairs bot — market data, market orders,
trade management. Mirrors the MR bot's client (same retry behaviour) plus a
market-order helper. Account-scoped reads are filtered by instrument so this bot
never confuses the MR bot's positions for its own."""

import time
import requests
import pandas as pd
import config

_BASE    = config.OANDA_BASE_URL
_HEADERS = {'Authorization': f'Bearer {config.OANDA_TOKEN}',
            'Content-Type':  'application/json'}

_RETRY_STATUSES   = {500, 502, 503, 504}
_RETRY_EXCEPTIONS = (requests.exceptions.SSLError, requests.exceptions.ReadTimeout,
                     requests.exceptions.ConnectionError)
_RETRY_DELAYS = [5, 15, 30]


def _request(method: str, path: str, **kwargs) -> dict:
    url = f'{_BASE}{path}'
    last_exc = None
    for delay in [0] + _RETRY_DELAYS:
        if delay:
            time.sleep(delay)
        try:
            r = getattr(requests, method)(url, headers=_HEADERS, timeout=15, **kwargs)
        except _RETRY_EXCEPTIONS:
            last_exc = True
            continue
        if r.status_code not in _RETRY_STATUSES:
            break
    else:
        if last_exc:
            raise requests.exceptions.ConnectionError(
                f'OANDA request failed after retries: {method.upper()} {path}')
    r.raise_for_status()
    return r.json()


def _get(path, params=None): return _request('get', path, params=params)
def _post(path, body):       return _request('post', path, json=body)
def _put(path, body):        return _request('put', path, json=body)


# ── Market data ───────────────────────────────────────────────────────────────

def get_candles(instrument: str, granularity: str, count: int) -> pd.DataFrame:
    """Last `count` COMPLETED candles as an OHLC DataFrame (incomplete dropped)."""
    data = _get(f'/v3/instruments/{instrument}/candles',
                {'granularity': granularity, 'count': count + 1, 'price': 'M'})
    rows = []
    for c in data['candles']:
        if not c.get('complete', True):
            continue
        m = c['mid']
        rows.append({'timestamp': pd.Timestamp(c['time'], tz='UTC'),
                     'open': float(m['o']), 'high': float(m['h']),
                     'low': float(m['l']), 'close': float(m['c'])})
    return pd.DataFrame(rows).set_index('timestamp')


# ── Account ───────────────────────────────────────────────────────────────────

def get_account_summary() -> dict:
    return _get(f'/v3/accounts/{config.OANDA_ACCOUNT}/summary')['account']


# ── Margin ────────────────────────────────────────────────────────────────────
# EUR_GBP is 5% / 20:1 — 5,000 units is ~$287, not the ~$115 originally assumed.
# On the shared account that is enough to collide with the MR bot's positions
# (txn 129, 2026-07-16, rejected INSUFFICIENT_MARGIN).

_margin_rate: dict[str, float] = {}


def get_margin_rate(instrument: str) -> float:
    """Live margin rate for an instrument (e.g. 0.05), cached for the process."""
    if instrument in _margin_rate:
        return _margin_rate[instrument]
    try:
        data = _get(f'/v3/accounts/{config.OANDA_ACCOUNT}/instruments',
                    {'instruments': instrument})
        rate = float(data['instruments'][0]['marginRate'])
    except Exception:
        rate = config.MARGIN_RATE_FALLBACK
    _margin_rate[instrument] = rate
    return rate


def _base_to_usd(instrument: str) -> float:
    """Conversion rate from the instrument's BASE currency into USD."""
    base = instrument.split('_')[0]
    if base == 'USD':
        return 1.0
    df = get_candles(f'{base}_USD', 'S5', 2)
    return float(df.iloc[-1]['close'])


def check_margin(instrument: str, units: int) -> tuple[bool, float, float]:
    """
    Return (ok, required, available) with config.MARGIN_SAFETY_FACTOR applied.

    Any failure to establish either figure returns ok=False — declining to trade
    on unknown margin state is the safe direction.
    """
    try:
        required  = abs(units) * _base_to_usd(instrument) * get_margin_rate(instrument)
        available = float(get_account_summary()['marginAvailable'])
    except Exception:
        return False, 0.0, 0.0
    return (required * config.MARGIN_SAFETY_FACTOR) <= available, required, available


# ── Orders / trades ───────────────────────────────────────────────────────────

def place_market_order(direction: str, units: int, sl_price: float,
                       instrument: str) -> dict:
    """Market order with a stop-loss on fill. units positive; sign from direction."""
    signed = -units if direction == 'short' else units
    body = {'order': {
        'type':        'MARKET',
        'instrument':  instrument,
        'units':       str(signed),
        'timeInForce': 'FOK',
        'positionFill': 'DEFAULT',
        'stopLossOnFill': {'price': f'{sl_price:.5f}', 'timeInForce': 'GTC'},
    }}
    return _post(f'/v3/accounts/{config.OANDA_ACCOUNT}/orders', body)


def get_open_trades(instrument: str = None) -> list[dict]:
    trades = _get(f'/v3/accounts/{config.OANDA_ACCOUNT}/openTrades').get('trades', [])
    if instrument:
        trades = [t for t in trades if t.get('instrument') == instrument]
    return trades


def get_trade(trade_id: str) -> dict:
    return _get(f'/v3/accounts/{config.OANDA_ACCOUNT}/trades/{trade_id}')['trade']


def close_trade(trade_id: str) -> dict:
    return _put(f'/v3/accounts/{config.OANDA_ACCOUNT}/trades/{trade_id}/close', {})
