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
        # 8,000 not 10,000 — GBP_USD carries a 5% margin rate, so 10k units cost
        # ~$669 (67% of a $1,000 account). 8k costs ~$535 and keeps peak margin
        # (MR + pairs bot) near 82%. See decisions/0003-margin-budget-small-account.md.
        'units_total':    8_000,
        'units_partial':  4_000,
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
        # 8,000 not 10,000 — GBP base, 5% margin rate. Same reasoning as GBPUSD.
        'units_total':    8_000,
        'units_partial':  4_000,
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
# Reduced 2 → 1 on 2026-07-30. On a $1,000 account the 2-position cap was never
# actually reachable with a GBP pair involved (2 × GBP @10k = $1,339 = 134% of the
# account) and had never once been exercised — 0 concurrent-position overlaps across
# 12 live trades. Its only observed effect was letting a second signal kill the
# first at fill time (txn 82). See decisions/0003-margin-budget-small-account.md.
MAX_CONCURRENT_POSITIONS = int(os.environ.get('MAX_CONCURRENT_POSITIONS', 1))

# ── Margin ───────────────────────────────────────────────────────────────────
# Fallbacks only — oanda_client.get_margin_rate() reads the live rate per
# instrument and uses these if the lookup fails. GBP-based crosses are 20:1;
# EUR_USD / USD_CAD are 50:1.
MARGIN_RATES = {
    'GBP_USD': 0.05,
    'GBP_JPY': 0.05,
    'EUR_GBP': 0.05,
    'EUR_USD': 0.02,
    'USD_CAD': 0.02,
}
# Used when an instrument is absent from the map above: assume the expensive rate
# rather than the cheap one, so an unknown instrument can't overdraw margin.
MARGIN_RATE_FALLBACK = 0.05

# Require this multiple of the raw margin requirement to be available before
# opening. 1.25 keeps peak utilisation near 80% of the account, which both leaves
# headroom for the pairs bot on the shared account and avoids sitting at the
# capacity ceiling where any adverse move blocks all further trading.
MARGIN_SAFETY_FACTOR = float(os.environ.get('MARGIN_SAFETY_FACTOR', 1.25))

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
# 48h since v1.10.0 — see docs/research_timestop_tuning.md and ADR-0002. The 24h
# cap was cutting wide-range setups before they could reach targets that scale off
# the entry range (TP2 sits at ~1x range). 48h captures the whole available gain:
# in the filtered backtest 48h, 72h and no-cap score identically.
MAX_HOLD_HOURS   = int(os.environ.get('MAX_HOLD_HOURS', 48))

# ── Candle history for filters ────────────────────────────────────────────────
M15_LOOKBACK   = 200
H4_LOOKBACK    = 60
DAILY_LOOKBACK = 10   # completed daily candles needed for pivot assignment

# ── Logging ──────────────────────────────────────────────────────────────────
LOG_DIR = os.environ.get('LOG_DIR', os.path.join(os.path.dirname(__file__), '..', 'logs'))
