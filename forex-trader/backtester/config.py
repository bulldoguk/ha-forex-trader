INSTRUMENTS = {
    'GBPUSD': 'GBPUSD=X',
    'GBPJPY': 'GBPJPY=X',
    'GBPEUR': 'GBPEUR=X',
    'GOLD':   'GC=F',
    'SPX':    '^GSPC',
    'FTSE':   '^FTSE',
}

# Timeframes
PIVOT_TF   = '4h'    # source candle for pivot calculation
SIGNAL_TF  = '15min' # chart timeframe for entry signals

# Trade sizing
LOT_SIZE   = 0.5     # lots per trade leg
NUM_LEGS   = 2       # always 2 legs per entry

# Pip value fallback (used when broker pip size unknown)
DEFAULT_PIP = {
    'GBPUSD': 0.0001,
    'GBPJPY': 0.01,
    'GBPEUR': 0.0001,
    'GOLD':   0.10,
    'SPX':    1.0,
    'FTSE':   1.0,
}

# How far back to fetch data (yfinance M15 max = 60 days)
LOOKBACK_DAYS = 59

# ---------------------------------------------------------------------------
# Filter configuration
# ---------------------------------------------------------------------------

FILTER_CFG = {
    # Minimum R8/S0 → P4 distance in price units (0 = disabled)
    # Recalibrated from wick-based detection on real (non-boundary) signals:
    # win rate flips strongly positive above 41 pips (0.0041).
    # Medium range (28-41 pips) is the worst bucket — avoid.
    'min_range_threshold': 0.0041,

    # Only enter during London and/or New York sessions (UTC)
    # London 08-17 UTC, New York 13-22 UTC — combined window 08-22 UTC
    'use_session': True,
    'active_sessions': ('london', 'newyork'),
    # Note: for Gold/indices you may want to disable or widen this filter

    # Linear regression channel: signal bar must be outside z_threshold std devs
    'use_channel': True,
    'channel_lookback': 60,   # M15 bars (~15 hours)
    'channel_z': 0.3,         # z-score threshold (0.3 = moderately extended)

    # Fibonacci: R8/S0 must land within tolerance of a key Fib level
    # tolerance is % of the swing range — needs to be generous since R8/S0
    # are pivot-derived and only approximately coincide with Fib levels
    'use_fibonacci': True,
    'fib_lookback': 120,          # M15 bars (~30 hours)
    'fib_tolerance_pct': 5.0,     # % of swing range — R8/S0 are extension levels,
                                  # need generous tolerance to find Fib confluence
}
