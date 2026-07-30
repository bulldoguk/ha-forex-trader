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

_RETRY_STATUSES    = {500, 502, 503, 504}
_RETRY_EXCEPTIONS  = (
    requests.exceptions.SSLError,
    requests.exceptions.ReadTimeout,
    requests.exceptions.ConnectionError,
)
_RETRY_DELAYS = [5, 15, 30]   # seconds between attempts


# ── Connection health ─────────────────────────────────────────────────────────
# Tracked at the HTTP layer so it captures EVERY OANDA failure regardless of which
# caller swallows the exception — the per-instrument handlers in trader.py and
# monitor.py catch-and-continue to stay resilient, which is exactly why a revoked
# token went unnoticed for ~17h on 2026-07-15. The daemon consults get_health()
# once per loop to alert on sustained auth/connection loss.
_health = {
    'last_success': None,          # datetime (UTC) of the last 2xx OANDA call
    'consecutive_failures': 0,     # OANDA calls failed in a row since last success
    'last_status': None,           # last HTTP status seen (int), or None on transport error
    'last_error': None,            # short description of the most recent failure
}


def _record_success(status: int) -> None:
    _health['last_success'] = datetime.now(timezone.utc)
    _health['consecutive_failures'] = 0
    _health['last_status'] = status
    _health['last_error'] = None


def _record_failure(status, detail: str) -> None:
    _health['consecutive_failures'] += 1
    _health['last_status'] = status
    _health['last_error'] = detail


def get_health() -> dict:
    """Snapshot of OANDA connection health for the daemon's watchdog."""
    h = dict(_health)
    last = h['last_success']
    h['seconds_since_success'] = (
        (datetime.now(timezone.utc) - last).total_seconds() if last else None
    )
    return h


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
            _record_failure(None, f'connection error after retries: {method.upper()} {path}')
            raise requests.exceptions.ConnectionError(
                f'OANDA request failed after retries: {method.upper()} {path}'
            )
    try:
        r.raise_for_status()
    except requests.exceptions.HTTPError as exc:
        _record_failure(r.status_code, f'HTTP {r.status_code}: {exc}')
        raise
    _record_success(r.status_code)
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


# ── Margin ───────────────────────────────────────────────────────────────────
# OANDA margin rates are NOT uniform: GBP-based instruments (and EUR_GBP) are
# 5% / 20:1, while EUR_USD and USD_CAD are 2% / 50:1. One GBP position at 10,000
# units costs ~$669 — 67% of a $1,000 account — which is what silently killed a
# GBP_JPY limit order on 2026-07-01 (txn 82) and an EUR_GBP entry on 2026-07-16
# (txn 129). Rates are read live and cached, with config.MARGIN_RATES as fallback
# so a failed lookup can never silently under-estimate the requirement.

_margin_rate_cache: dict[str, float] = {}


def get_margin_rate(instrument: str) -> float:
    """Live margin rate for an instrument (e.g. 0.05), cached for the process."""
    if instrument in _margin_rate_cache:
        return _margin_rate_cache[instrument]
    try:
        data = _get(f'/v3/accounts/{config.OANDA_ACCOUNT}/instruments',
                    {'instruments': instrument})
        rate = float(data['instruments'][0]['marginRate'])
    except Exception:
        rate = config.MARGIN_RATES.get(instrument, config.MARGIN_RATE_FALLBACK)
    _margin_rate_cache[instrument] = rate
    return rate


def _base_to_usd(instrument: str) -> float:
    """Conversion rate from an instrument's BASE currency into USD."""
    base = instrument.split('_')[0]
    if base == 'USD':
        return 1.0
    return get_current_price(f'{base}_USD')


def margin_required(instrument: str, units: int) -> float:
    """Estimated margin in account currency (USD) to hold `units` of `instrument`."""
    return abs(units) * _base_to_usd(instrument) * get_margin_rate(instrument)


def check_margin(instrument: str, units: int) -> tuple[bool, float, float]:
    """
    Return (ok, required, available).

    `ok` applies config.MARGIN_SAFETY_FACTOR on top of the raw requirement so we
    never open a position that leaves the account with no room to breathe. Any
    failure to determine either figure returns ok=False — refusing to trade on
    unknown margin state is the safe direction.
    """
    try:
        required  = margin_required(instrument, units)
        available = float(get_account_summary()['marginAvailable'])
    except Exception:
        return False, 0.0, 0.0
    return (required * config.MARGIN_SAFETY_FACTOR) <= available, required, available


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


def get_order(order_id: str) -> dict:
    """Fetch a single order by id — including terminal ones.

    `state` is the useful field: FILLED (with `tradeOpenedID`) vs CANCELLED. This
    is what distinguishes "filled and closed between two scans" from "rejected by
    the broker"; `get_pending_orders` alone cannot tell them apart.
    """
    return _get(f'/v3/accounts/{config.OANDA_ACCOUNT}/orders/{order_id}')['order']


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
