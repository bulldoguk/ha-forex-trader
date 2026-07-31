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

# Holding-time cap (M15 bars). Mirrors the live daemon's MAX_HOLD_HOURS (48h).
# 192 bars = 48h (was 96/24h before v1.10.0). Any leg still open at the cap is
# marked-to-market at that bar's close, exactly as the live time-stop force-closes
# at market. This keeps the backtest honest: without it, simulate() held positions
# indefinitely until price eventually reverted, which manufactured a fake edge on
# daily-pivot instruments (USDJPY: 85% win uncapped → 40% at 1-day cap). See
# ../decisions/0002-remove-usdjpy-eurjpy-holding-time-artifact.md and
# ../docs/research_timestop_tuning.md for the 24h → 48h widening.
MAX_HOLD_BARS = 192

# Pip value fallback (used when broker pip size unknown)
DEFAULT_PIP = {
    'GBPUSD': 0.0001,
    'GBPJPY': 0.01,
    'GBPEUR': 0.0001,
    'USDJPY': 0.01,
    'USDCHF': 0.0001,
    'USDCAD': 0.0001,
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
    'GBPUSD': {
        # Donchian trend filter backtested on 2yr data: win rate 57%→64%, expectancy
        # +0.00204→+0.00301, max DD -0.027→-0.004 (84% reduction). N=120 4H bars (~1 month).
        # Standard filters deliberately omitted — the default FILTER_CFG applies for those.
        'min_range_threshold': 0.0041,
        'use_session':  True,
        'active_sessions': ('london', 'newyork'),
        'use_channel':  True,  'channel_lookback': 60, 'channel_z': 0.3,
        'use_fibonacci': True, 'fib_lookback': 120, 'fib_tolerance_pct': 5.0,
        'use_donchian_trend': True,
    },
    'USDJPY': {
        # Starting threshold: 50 pips (0.50 price units at 0.01/pip).
        # Calibrate via range-bucket output — look for win-rate flip point.
        'min_range_threshold': 0.50,
        'use_session':  True,
        'active_sessions': ('tokyo', 'london', 'newyork'),
        'use_channel':  True,  'channel_lookback': 60, 'channel_z': 0.3,
        'use_fibonacci': True, 'fib_lookback': 120, 'fib_tolerance_pct': 5.0,
    },
    'AUDJPY': {
        # min_range_threshold=0: calibrate from range-bucket analysis after backtest.
        # AUD/JPY typical daily range 50-80 pips; expect flip somewhere in that band.
        'min_range_threshold': 0,
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
    'USDCAD': {
        # Notch filter: skip the 40-51 pip dead zone (29% win, -0.00109 avg in unfiltered).
        # Tight/medium (<40 pips) and very wide (>51 pips) both have positive edge.
        'notch_range_lo': 0.0040,
        'notch_range_hi': 0.0051,
        'use_session':  True,
        'active_sessions': ('london', 'newyork'),
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
