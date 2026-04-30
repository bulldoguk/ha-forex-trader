"""OANDA v20 REST API wrapper — order placement, position management, market data."""

import time
import requests
import pandas as pd
from datetime import datetime, timezone
import config

_BASE    = config.OANDA_BASE_URL
_HEADERS = {
    'Authorization': f'Bearer {config.OANDA_TOKEN}',
    'Content-Type':  'application/json',
}

_RETRY_STATUSES = {500, 502, 503, 504}
_RETRY_DELAYS   = [5, 15, 30]   # seconds between attempts


def _request(method: str, path: str, **kwargs) -> dict:
    url = f'{_BASE}{path}'
    for attempt, delay in enumerate([0] + _RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        r = getattr(requests, method)(url, headers=_HEADERS, timeout=15, **kwargs)
        if r.status_code not in _RETRY_STATUSES:
            break
    r.raise_for_status()
    return r.json()


def _get(path: str, params: dict = None) -> dict:
    return _request('get', path, params=params)


def _post(path: str, body: dict) -> dict:
    return _request('post', path, json=body)


def _put(path: str, body: dict) -> dict:
    return _request('put', path, json=body)


# ── Market data ──────────────────────────────────────────────────────────────

def get_candles(instrument: str, granularity: str, count: int) -> pd.DataFrame:
    """Fetch the last `count` completed candles. Returns OHLC DataFrame."""
    data = _get(f'/v3/instruments/{instrument}/candles', {
        'granularity': granularity,
        'count':       count + 1,   # +1 because the latest may be incomplete
        'price':       'M',
    })
    rows = []
    for c in data['candles']:
        if not c.get('complete', True):
            continue
        mid = c['mid']
        rows.append({
            'timestamp': pd.Timestamp(c['time'], tz='UTC'),
            'open':  float(mid['o']),
            'high':  float(mid['h']),
            'low':   float(mid['l']),
            'close': float(mid['c']),
            'volume': int(c.get('volume', 0)),
        })
    return pd.DataFrame(rows).set_index('timestamp')


def get_current_price(instrument: str) -> float:
    """Return the latest mid price."""
    df = get_candles(instrument, 'S5', 2)   # 5-second candles
    return float(df.iloc[-1]['close'])


# ── Account ──────────────────────────────────────────────────────────────────

def get_account_summary() -> dict:
    return _get(f'/v3/accounts/{config.OANDA_ACCOUNT}/summary')['account']


# ── Orders ───────────────────────────────────────────────────────────────────

def place_limit_order(direction: str, price: float, units: int,
                      sl_price: float, instrument: str = None) -> dict:
    """
    Place a GTC limit order.
    direction: 'short' or 'long'
    units: always positive — function handles sign
    instrument: OANDA instrument code (e.g. 'GBP_USD'); falls back to config default
    """
    instr        = instrument or 'GBP_USD'
    signed_units = -units if direction == 'short' else units
    # Gold and other instruments may need fewer decimal places
    price_fmt    = f'{price:.5f}' if price < 100 else f'{price:.3f}'
    sl_fmt       = f'{sl_price:.5f}' if sl_price < 100 else f'{sl_price:.3f}'
    body = {
        'order': {
            'type':        'LIMIT',
            'instrument':  instr,
            'units':       str(signed_units),
            'price':       price_fmt,
            'timeInForce': 'GTC',
            'stopLossOnFill': {
                'price':       sl_fmt,
                'timeInForce': 'GTC',
            },
        }
    }
    return _post(f'/v3/accounts/{config.OANDA_ACCOUNT}/orders', body)


def cancel_order(order_id: str) -> dict:
    return _put(f'/v3/accounts/{config.OANDA_ACCOUNT}/orders/{order_id}/cancel', {})


def get_pending_orders(instrument: str = None) -> list[dict]:
    data = _get(f'/v3/accounts/{config.OANDA_ACCOUNT}/pendingOrders')
    orders = data.get('orders', [])
    if instrument:
        orders = [o for o in orders if o.get('instrument') == instrument]
    return orders


# ── Trades ───────────────────────────────────────────────────────────────────

def get_open_trades(instrument: str = None) -> list[dict]:
    data = _get(f'/v3/accounts/{config.OANDA_ACCOUNT}/openTrades')
    trades = data.get('trades', [])
    if instrument:
        trades = [t for t in trades if t.get('instrument') == instrument]
    return trades


def get_trade(trade_id: str) -> dict:
    return _get(f'/v3/accounts/{config.OANDA_ACCOUNT}/trades/{trade_id}')['trade']


def modify_sl(trade_id: str, sl_price: float) -> dict:
    return _put(
        f'/v3/accounts/{config.OANDA_ACCOUNT}/trades/{trade_id}/orders',
        {'stopLoss': {'price': f'{sl_price:.5f}', 'timeInForce': 'GTC'}},
    )


def partial_close(trade_id: str, units: int) -> dict:
    """Close `units` of an open trade (always positive integer)."""
    return _put(
        f'/v3/accounts/{config.OANDA_ACCOUNT}/trades/{trade_id}/close',
        {'units': str(units)},
    )


def close_trade(trade_id: str) -> dict:
    return _put(
        f'/v3/accounts/{config.OANDA_ACCOUNT}/trades/{trade_id}/close',
        {},
    )
