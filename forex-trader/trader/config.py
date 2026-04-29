import os, sys
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

# Allow imports from backtester/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backtester'))

# ── OANDA ────────────────────────────────────────────────────────────────────
OANDA_TOKEN    = os.environ['OANDA_API_TOKEN']
OANDA_ACCOUNT  = os.environ['OANDA_ACCOUNT_ID']
OANDA_BASE_URL = 'https://api-fxpractice.oanda.com'

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
    # GOLD: disabled — negative expectancy (−$7.41/trade) across all range
    # buckets on 1-year wick-based backtest. Mean-reversion does not appear
    # reliable for XAU/USD with 4H pivot levels. Re-evaluate with longer data
    # or a different entry model before re-enabling.
    # 'GOLD': {
    #     'oanda': 'XAU_USD',
    #     'units_total':   2,
    #     'units_partial': 1,
    #     'pip_size':      1.0,
    #     'filter_cfg': { ... },
    # },
}

# ── Timing ───────────────────────────────────────────────────────────────────
SCAN_DELAY_SECS  = 60    # seconds after M15 close before scanning
MONITOR_INTERVAL = 60    # seconds between position checks
LIMIT_ORDER_TTL  = 4     # M15 bars before unfilled limit is cancelled

# ── Candle history for filters ────────────────────────────────────────────────
M15_LOOKBACK = 200
H4_LOOKBACK  = 60

# ── Logging ──────────────────────────────────────────────────────────────────
LOG_DIR = os.path.join(os.path.dirname(__file__), '..', 'logs')
