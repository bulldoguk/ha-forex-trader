import os, sys
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

# Allow imports from backtester/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backtester'))

# ── OANDA ────────────────────────────────────────────────────────────────────
OANDA_TOKEN    = os.environ['OANDA_API_TOKEN']
OANDA_ACCOUNT  = os.environ['OANDA_ACCOUNT_ID']
OANDA_BASE_URL = ('https://api-fxtrade.oanda.com'
                  if os.environ.get('OANDA_ENV', 'practice') == 'live'
                  else 'https://api-fxpractice.oanda.com')

# ── Gmail ────────────────────────────────────────────────────────────────────
GMAIL_FROM     = os.environ['GMAIL_FROM_EMAIL']
GMAIL_PASSWORD = os.environ['GMAIL_APP_PASSWORD']
NOTIFY_TO      = os.environ['NOTIFY_EMAIL']

# ── Instrument definitions ───────────────────────────────────────────────────
# units_total / units_partial: OANDA units (not lots)
#   GBP_USD / EUR_USD : 10,000 units = 0.1 lot  → $1/pip
#   XAU_USD           : 2 units = 2 oz           → $2/point
#
# pip_size: used to convert price delta → display pips in notifications
#   forex 4-decimal: 0.0001
#   gold:            1.0  (we report in $/oz points, not sub-cent pips)

INSTRUMENTS = {
    'GBPUSD': {
        'oanda': 'GBP_USD',
        'units_total':   10_000,
        'units_partial':  5_000,
        'pip_size':      0.0001,
        'filter_cfg': {
            'min_range_threshold': 0.0041,   # 41 pips — recalibrated from wick-based detection
            'use_session':  True,
            'active_sessions': ('london', 'newyork'),
            'use_channel':  True,  'channel_lookback': 60, 'channel_z': 0.3,
            'use_fibonacci': True, 'fib_lookback': 120, 'fib_tolerance_pct': 5.0,
        },
    },
    'EURUSD': {
        'oanda': 'EUR_USD',
        'units_total':   10_000,
        'units_partial':  5_000,
        'pip_size':      0.0001,
        'filter_cfg': {
            'min_range_threshold': 0.0041,   # same as GBPUSD — recalibrated
            'use_session':  True,
            'active_sessions': ('london', 'newyork'),
            'use_channel':  True,  'channel_lookback': 60, 'channel_z': 0.3,
            'use_fibonacci': True, 'fib_lookback': 120, 'fib_tolerance_pct': 5.0,
        },
    },
    'GBPJPY': {
        'oanda': 'GBP_JPY',
        'units_total':   10_000,
        'units_partial':  5_000,
        'pip_size':      0.01,    # JPY pair — 1 pip = 0.01
        'filter_cfg': {
            'min_range_threshold': 0.86,  # 86 pips in JPY terms — top quartile only
            'use_session':  True,
            'active_sessions': ('london', 'newyork'),
            'use_channel':  True,  'channel_lookback': 60, 'channel_z': 0.3,
            'use_fibonacci': True, 'fib_lookback': 120, 'fib_tolerance_pct': 5.0,
        },
    },
    # USDJPY: removed 2026-07-01 — no genuine intraday edge on either timeframe.
    #   Daily pivots: backtest showed 85% win / +164 pips, but that was an artifact
    #     of the backtester's unlimited holding time (median winning hold 2.4 days).
    #     Under a realistic 1-day cap the edge collapsed to 40% win / +47 pips
    #     (shorts 81%→31%). Both live trades (Trade 5, Trade 6) were shorts stopped
    #     out mid-swing — exactly this failure mode.
    #   4h pivots: genuinely intraday but a proven loser at every range threshold
    #     (36% win, −9 to −14 pips/trade, both directions).
    #   See decisions/0002-remove-usdjpy-eurjpy-holding-time-artifact.md.
    'USDCAD': {
        'oanda': 'USD_CAD',
        'units_total':   10_000,
        'units_partial':  5_000,
        'pip_size':      0.0001,
        'filter_cfg': {
            # Notch filter: skip 40-51 pip dead zone (29% win, -0.00109 avg unfiltered).
            # Tight/medium (<40 pips) and very wide (>51 pips) both carry positive edge.
            'notch_range_lo': 0.0040,
            'notch_range_hi': 0.0051,
            'use_session':  True,
            'active_sessions': ('london', 'newyork'),
            'use_channel':  True,  'channel_lookback': 60, 'channel_z': 0.3,
            'use_fibonacci': True, 'fib_lookback': 120, 'fib_tolerance_pct': 5.0,
        },
    },
    # EURJPY: removed 2026-07-01 — daily pivots produced only 4 signals in 3 years
    #   (effectively inactive) and shares USDJPY's daily-pivot multi-day-hold risk
    #   profile with far too little data to justify. Pulled alongside USDJPY.
    #   See decisions/0002-remove-usdjpy-eurjpy-holding-time-artifact.md.
    # GOLD: disabled — negative expectancy across all tested configurations:
    #   4H pivots R4/S4:    −$7.41/trade  (35 trades, 1yr)
    #   Daily pivots R4/S4:  3 signals/yr  (levels too extended for gold's range)
    #   Daily pivots R2/S2: −$11.99/trade (116 trades, 2yr) — 1yr wide-bucket
    #                        result (86% win) was 2025 bull-run noise, not edge.
    # Mean-reversion pivot model does not appear reliable for XAU/USD.
    # 'GOLD': {
    #     'oanda': 'XAU_USD',
    #     'units_total':   2,
    #     'units_partial': 1,
    #     'pip_size':      1.0,
    #     'entry_level':   'R2',
    #     'filter_cfg': { ... },
    # },
}

# ── Position limits ──────────────────────────────────────────────────────────
MAX_CONCURRENT_POSITIONS = 2   # discard new signals when this many are pending/filled

# ── Connection-health watchdog ────────────────────────────────────────────────
# Alert (one email per hour, via notifier's per-context cooldown) once OANDA calls
# have failed this many times in a row. Catches token revocation / auth loss /
# network outage that the per-instrument handlers otherwise swallow silently — the
# 2026-07-15 failure mode. A sustained outage produces several failures per loop,
# so 3 fires on roughly the first fully-failed monitor cycle (~60s).
CONN_FAILURE_ALERT_THRESHOLD = int(os.environ.get('CONN_FAILURE_ALERT_THRESHOLD', 3))

# ── Timing ───────────────────────────────────────────────────────────────────
SCAN_DELAY_SECS  = 60    # seconds after M15 close before scanning
MONITOR_INTERVAL = 60    # seconds between position checks
LIMIT_ORDER_TTL  = 4     # M15 bars before unfilled limit is cancelled

# Time-stop: force-close a still-open position this many hours after fill.
# The strategy is intraday mean-reversion; the robust instruments (GBPUSD, USDCAD)
# close within a day. Capping the hold keeps live behaviour honest and prevents
# the multi-day "wait for reversion" drift that flattered the USDJPY daily-pivot
# backtest (see decisions/0002). 24h leaves genuine intraday trades untouched.
MAX_HOLD_HOURS   = int(os.environ.get('MAX_HOLD_HOURS', 24))

# ── Candle history for filters ────────────────────────────────────────────────
M15_LOOKBACK   = 200
H4_LOOKBACK    = 60
DAILY_LOOKBACK = 10   # completed daily candles needed for pivot assignment

# ── Logging ──────────────────────────────────────────────────────────────────
LOG_DIR = os.environ.get('LOG_DIR', os.path.join(os.path.dirname(__file__), '..', 'logs'))
