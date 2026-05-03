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
    'USDJPY': 0.01,
    'GOLD':   0.10,
    'SPX':    1.0,
    'FTSE':   1.0,
}

# How far back to fetch data (yfinance M15 max = 60 days)
LOOKBACK_DAYS = 59

# ---------------------------------------------------------------------------
# Filter configuration
# ---------------------------------------------------------------------------

# Per-instrument filter overrides (used when instrument needs different settings)
FILTER_CFG_OVERRIDES = {
    'USDJPY': {
        # Starting threshold: 50 pips (0.50 price units at 0.01/pip).
        # Calibrate via range-bucket output — look for win-rate flip point.
        'min_range_threshold': 0.50,
        'use_session':  True,
        'active_sessions': ('tokyo', 'london', 'newyork'),
        'use_channel':  True,  'channel_lookback': 60, 'channel_z': 0.3,
        'use_fibonacci': True, 'fib_lookback': 120, 'fib_tolerance_pct': 5.0,
    },
    'EURJPY': {
        # Calibrated from range-bucket analysis: win rate flips at 0.50 (50 pips).
        # Wide bucket (0.50-0.58): 67% win rate. Very wide (>0.58): 43%, +0.13 avg.
        'min_range_threshold': 0.50,
        'use_session':  True,
        'active_sessions': ('tokyo', 'london', 'newyork'),
        'use_channel':  True,  'channel_lookback': 60, 'channel_z': 0.3,
        'use_fibonacci': True, 'fib_lookback': 120, 'fib_tolerance_pct': 5.0,
    },
    'GOLD': {
        # R2 entry (R6 in strategy naming = first extension level) instead of R4.
        # Daily pivots: R4/S4 are too extended for gold's range to reach reliably.
        # R2/S2 align better with London/NY fix order flow clustering.
        # min_range_threshold=0: calibrate from range-bucket analysis after backtest.
        'entry_level': 'R2',
        'min_range_threshold': 0,
        'use_session':  True,
        'active_sessions': ('london', 'newyork'),
        'use_channel':  True,  'channel_lookback': 60, 'channel_z': 0.3,
        'use_fibonacci': True, 'fib_lookback': 120, 'fib_tolerance_pct': 5.0,
    },
}

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
