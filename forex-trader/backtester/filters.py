"""
Signal filters applied before a trade is accepted.
Each filter returns True (pass) or False (reject).
All filters are independently togglable via config.
"""

import numpy as np
import pandas as pd

# Fib levels used for confluence check (retracement + extension)
_KEY_FIBS = [0.236, 0.382, 0.500, 0.618, 0.786, 1.000, 1.272, 1.618, 2.000, 2.618]

# London 08:00-17:00 UTC, New York 13:00-22:00 UTC, Tokyo 00:00-09:00 UTC
_SESSIONS = {
    'london':   (8,  17),
    'newyork':  (13, 22),
    'tokyo':    (0,   9),
}


# ---------------------------------------------------------------------------
# 1. Minimum range filter
# ---------------------------------------------------------------------------

def min_range(entry_range: float, threshold: float) -> bool:
    """R8/S0 → P4 distance must exceed threshold (in price units)."""
    return entry_range >= threshold


def max_range(entry_range: float, threshold: float) -> bool:
    """R8/S0 → P4 distance must not exceed threshold (used for Gold)."""
    return entry_range <= threshold


def notch_range(entry_range: float, lo: float, hi: float) -> bool:
    """Reject signals whose range falls in the dead zone [lo, hi]."""
    return not (lo <= entry_range <= hi)


# ---------------------------------------------------------------------------
# 2. Session filter
# ---------------------------------------------------------------------------

def session(ts, active: tuple[str, ...] = ('london', 'newyork')) -> bool:
    """Signal must occur inside one of the active trading sessions (UTC)."""
    hour = ts.hour
    for name in active:
        start, end = _SESSIONS[name]
        if start <= hour < end:
            return True
    return False


# ---------------------------------------------------------------------------
# 3. Trend channel filter (linear regression)
# ---------------------------------------------------------------------------

def channel(df: pd.DataFrame, signal_idx: int, direction: str,
            lookback: int = 60, z_threshold: float = 0.5) -> bool:
    """
    Fits a linear regression to the last `lookback` M15 closes.
    Short signals pass when the signal bar is in the upper portion of
    the channel (z-score > z_threshold); long signals when in lower portion.
    Ensures we're fading price that is genuinely extended relative to recent trend.
    """
    start = max(0, signal_idx - lookback)
    window = df.iloc[start:signal_idx]
    if len(window) < 10:
        return True  # not enough data — pass through

    closes = window['close'].values
    x = np.arange(len(closes))
    slope, intercept = np.polyfit(x, closes, 1)

    residuals = closes - (slope * x + intercept)
    std = residuals.std()
    if std < 1e-10:
        return True

    # Where does the signal bar sit relative to the channel?
    signal_close = df.iloc[signal_idx]['close']
    trend_at_signal = slope * len(closes) + intercept
    z = (signal_close - trend_at_signal) / std

    if direction == 'short':
        return z > z_threshold    # extended above channel → valid short
    else:
        return z < -z_threshold   # extended below channel → valid long


# ---------------------------------------------------------------------------
# 4. Fibonacci confluence filter
# ---------------------------------------------------------------------------

def fibonacci(df: pd.DataFrame, signal_idx: int, level_price: float,
              direction: str, lookback: int = 120,
              tolerance_pct: float = 0.15) -> bool:
    """
    Draws a Fibonacci grid from the recent swing high/low within `lookback` bars.
    Passes if `level_price` (R8 for short, S0 for long) falls within
    `tolerance_pct`% of the swing range from any key Fib level.

    For shorts: Fib drawn UP from swing low to swing high; we look for
    extension levels (>1.0) where R8 may act as resistance.
    For longs: inverse — we look for support at Fib levels below the swing.
    """
    start = max(0, signal_idx - lookback)
    window = df.iloc[start:signal_idx]
    if len(window) < 10:
        return True

    swing_high = window['high'].max()
    swing_low  = window['low'].min()
    swing_range = swing_high - swing_low
    if swing_range < 1e-10:
        return True

    tol = swing_range * (tolerance_pct / 100)

    if direction == 'short':
        # Fib levels measured UP from swing_low
        fib_prices = [swing_low + f * swing_range for f in _KEY_FIBS]
    else:
        # Fib levels measured DOWN from swing_high
        fib_prices = [swing_high - f * swing_range for f in _KEY_FIBS]

    return any(abs(level_price - fp) <= tol for fp in fib_prices)


# ---------------------------------------------------------------------------
# 5. Donchian trend alignment filter
# ---------------------------------------------------------------------------

def donchian_trend(dc_trend_val, direction: str) -> bool:
    """Pass only if signal direction matches the Donchian trend direction."""
    if dc_trend_val is None or (isinstance(dc_trend_val, float) and pd.isna(dc_trend_val)):
        return True  # no trend data yet — pass through
    return dc_trend_val == direction


# ---------------------------------------------------------------------------
# Composite: run all enabled filters for a signal
# ---------------------------------------------------------------------------

def apply_all(df: pd.DataFrame, signal_idx: int, direction: str,
              level_price: float, entry_range: float, ts,
              cfg: dict) -> tuple[bool, list[str]]:
    """
    Runs each enabled filter. Returns (passed: bool, failed_filters: list[str]).
    cfg keys: min_range_threshold, use_session, use_channel, use_fibonacci,
              channel_lookback, channel_z, fib_lookback, fib_tolerance_pct,
              active_sessions, use_donchian_trend.
    """
    failed = []

    # A filter only runs if its key is explicitly present in cfg
    if cfg.get('min_range_threshold', 0) > 0:
        if not min_range(entry_range, cfg['min_range_threshold']):
            failed.append('min_range')

    if cfg.get('max_range_threshold', 0) > 0:
        if not max_range(entry_range, cfg['max_range_threshold']):
            failed.append('max_range')

    if cfg.get('notch_range_lo') and cfg.get('notch_range_hi'):
        if not notch_range(entry_range, cfg['notch_range_lo'], cfg['notch_range_hi']):
            failed.append('notch_range')

    if cfg.get('use_session') is True:
        if not session(ts, cfg.get('active_sessions', ('london', 'newyork'))):
            failed.append('session')

    if cfg.get('use_channel') is True:
        if not channel(df, signal_idx, direction,
                       lookback=cfg.get('channel_lookback', 60),
                       z_threshold=cfg.get('channel_z', 0.5)):
            failed.append('channel')

    if cfg.get('use_fibonacci') is True:
        if not fibonacci(df, signal_idx, level_price, direction,
                         lookback=cfg.get('fib_lookback', 120),
                         tolerance_pct=cfg.get('fib_tolerance_pct', 0.15)):
            failed.append('fibonacci')

    if cfg.get('use_donchian_trend') is True:
        dc_val = df.iloc[signal_idx].get('dc_trend') if hasattr(df.iloc[signal_idx], 'get') \
                 else df.iloc[signal_idx]['dc_trend'] if 'dc_trend' in df.columns else None
        if not donchian_trend(dc_val, direction):
            failed.append('donchian_trend')

    return (len(failed) == 0, failed)
