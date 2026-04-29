"""
OANDA v20 REST API data fetcher.
Replaces yfinance — pulls M15 and 1H candles directly from OANDA practice account.
Supports multi-year history via paginated requests (5000 candles/request).
"""

import os
import time
import requests
import pandas as pd
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

_BASE  = "https://api-fxpractice.oanda.com"
_TOKEN = os.environ.get('OANDA_API_TOKEN', '')
_ACCT  = os.environ.get('OANDA_ACCOUNT_ID', '')

_HEADERS = {
    'Authorization': f'Bearer {_TOKEN}',
    'Content-Type':  'application/json',
}

# Map our instrument names to OANDA instrument codes
OANDA_INSTRUMENTS = {
    'GBPUSD': 'GBP_USD',
    'GBPJPY': 'GBP_JPY',
    'GBPEUR': 'EUR_GBP',   # OANDA uses EUR_GBP not GBP_EUR
    'EURUSD': 'EUR_USD',
    'GOLD':   'XAU_USD',
    'SPX':    'SPX500_USD',
    'FTSE':   'UK100_GBP',
}

# OANDA granularity codes
_GRAN = {
    '15min': 'M15',
    '1h':    'H1',
    '4h':    'H4',
}

_MAX_CANDLES = 5000   # OANDA hard limit per request


def fetch(instrument: str, days: int = 365) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Returns (m15_df, h4_df) for the given instrument name.
    Fetches `days` of history — OANDA supports multi-year pulls.
    """
    oanda_instr = OANDA_INSTRUMENTS.get(instrument)
    if not oanda_instr:
        raise ValueError(f"Unknown instrument: {instrument}. "
                         f"Available: {list(OANDA_INSTRUMENTS.keys())}")

    print(f"  Fetching M15 ({days}d)...", end=' ', flush=True)
    m15_raw = _fetch_candles(oanda_instr, 'M15', days)
    print(f"{len(m15_raw)} candles")

    print(f"  Fetching H4...", end=' ', flush=True)
    h4_raw  = _fetch_candles(oanda_instr, 'H4', days)
    print(f"{len(h4_raw)} candles")

    m15 = _to_dataframe(m15_raw)
    h4  = _to_dataframe(h4_raw, shift=True)   # shift so we use COMPLETED candle

    return m15, h4


def _fetch_candles(instrument: str, granularity: str, days: int) -> list[dict]:
    """Paginate backwards from now to collect `days` of candles."""
    end_dt   = datetime.now(timezone.utc)
    start_dt = end_dt - pd.Timedelta(days=days)

    all_candles: list[dict] = []
    page_end = end_dt

    while True:
        params = {
            'granularity': granularity,
            'count':       _MAX_CANDLES,
            'to':          page_end.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'price':       'M',   # midpoint candles
        }

        resp = requests.get(
            f"{_BASE}/v3/instruments/{instrument}/candles",
            headers=_HEADERS,
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        candles = resp.json().get('candles', [])

        if not candles:
            break

        # Filter to only complete candles
        candles = [c for c in candles if c.get('complete', True)]
        all_candles = candles + all_candles

        earliest = pd.Timestamp(candles[0]['time'], tz='UTC')
        if earliest <= start_dt:
            break

        # Step back one tick before the earliest candle
        page_end = earliest - pd.Timedelta(seconds=1)
        time.sleep(0.1)   # be polite to the API

    # Trim to requested window
    all_candles = [
        c for c in all_candles
        if pd.Timestamp(c['time'], tz='UTC') >= start_dt
    ]
    return all_candles


def _to_dataframe(candles: list[dict], shift: bool = False) -> pd.DataFrame:
    """Convert raw OANDA candle list to a clean OHLC DataFrame."""
    rows = []
    for c in candles:
        mid = c['mid']
        rows.append({
            'timestamp': pd.Timestamp(c['time'], tz='UTC'),
            'open':      float(mid['o']),
            'high':      float(mid['h']),
            'low':       float(mid['l']),
            'close':     float(mid['c']),
            'volume':    int(c.get('volume', 0)),
        })

    df = pd.DataFrame(rows).set_index('timestamp')

    if shift:
        # For pivot calculation: use the COMPLETED candle's H/L/C
        # so shift forward one period before forward-filling onto M15
        df = df.shift(1).dropna()

    return df


def account_summary() -> dict:
    """Fetch and return account summary (balance, NAV, open positions)."""
    resp = requests.get(
        f"{_BASE}/v3/accounts/{_ACCT}/summary",
        headers=_HEADERS,
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json().get('account', {})


def list_instruments() -> list[str]:
    """Return all tradeable instrument codes for this account."""
    resp = requests.get(
        f"{_BASE}/v3/accounts/{_ACCT}/instruments",
        headers=_HEADERS,
        timeout=10,
    )
    resp.raise_for_status()
    return [i['name'] for i in resp.json().get('instruments', [])]
