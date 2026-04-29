import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from config import LOOKBACK_DAYS, PIVOT_TF, SIGNAL_TF


def fetch(ticker: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Returns (m15_df, h4_df) for the given yfinance ticker.
    Both DataFrames have columns: open, high, low, close, volume.
    h4_df is resampled from 1h data and shifted so each row represents
    the COMPLETED 4h candle whose pivots apply going forward.
    """
    end   = datetime.utcnow()
    start = end - timedelta(days=LOOKBACK_DAYS)

    raw_15m = yf.download(ticker, start=start, end=end, interval='15m',
                          auto_adjust=True, progress=False)
    raw_1h  = yf.download(ticker, start=start, end=end, interval='1h',
                          auto_adjust=True, progress=False)

    if raw_15m.empty or raw_1h.empty:
        raise ValueError(f"No data returned for {ticker}")

    m15 = _clean(raw_15m)
    h4  = _to_4h(raw_1h)
    return m15, h4


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    # yfinance may return MultiIndex columns — flatten to the first level
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0].lower() for c in df.columns]
    else:
        df.columns = [c.lower() for c in df.columns]
    df.index = pd.to_datetime(df.index, utc=True)
    df = df[['open', 'high', 'low', 'close', 'volume']].dropna()
    return df


def _to_4h(df: pd.DataFrame) -> pd.DataFrame:
    df = _clean(df)
    h4 = df.resample('4h', closed='left', label='left').agg({
        'open':   'first',
        'high':   'max',
        'low':    'min',
        'close':  'last',
        'volume': 'sum',
    }).dropna()
    # Shift forward: pivots are calculated from the COMPLETED candle,
    # so the levels only become valid at the NEXT candle's open.
    h4 = h4.shift(1).dropna()
    return h4
