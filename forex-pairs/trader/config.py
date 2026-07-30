"""Config for the EUR/GBP pairs-reversion add-on. Credentials and tunables come
from environment variables (set by run.sh from HA add-on options); a local .env
is loaded as a fallback for dev/dry-run."""
import os
from dotenv import load_dotenv

# Dev fallback only — in the add-on container creds arrive as real env vars and
# this file is absent (load_dotenv is then a no-op).
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '..', '.env'))

# ── OANDA (SAME practice account as the MR bot — see the ADR) ──────────────────
OANDA_TOKEN    = os.environ['OANDA_API_TOKEN']
OANDA_ACCOUNT  = os.environ['OANDA_ACCOUNT_ID']
OANDA_BASE_URL = ('https://api-fxtrade.oanda.com'
                  if os.environ.get('OANDA_ENV', 'practice') == 'live'
                  else 'https://api-fxpractice.oanda.com')

# ── Gmail ─────────────────────────────────────────────────────────────────────
GMAIL_FROM     = os.environ.get('GMAIL_FROM_EMAIL', '')
GMAIL_PASSWORD = os.environ.get('GMAIL_APP_PASSWORD', '')
NOTIFY_TO      = os.environ.get('NOTIFY_EMAIL', '')

# ── Strategy instrument ───────────────────────────────────────────────────────
# EUR/GBP daily z-reversion. Sized conservatively by default: the bot shares the
# MR account, so keep margin small to avoid contention (see ADR margin note).
INSTRUMENT = 'EUR_GBP'
PIP_SIZE   = 0.0001
# NOTE: EUR_GBP is a 5% / 20:1 instrument, NOT 50:1. 5,000 units costs ~$287 of
# margin, not the ~$115 originally assumed here. Corrected 2026-07-30 after txn 129
# was rejected for INSUFFICIENT_MARGIN — see decisions/0003-margin-budget-small-account.md.
# Sized 2,600 (not 5,000) so the research doc's documented worst case (-331 bps)
# caps at ~10% of a $1,000 account instead of 19% — see decisions/0004.
UNITS      = int(os.environ.get('EURGBP_UNITS', '2600'))   # ~$149 margin at 20:1

# ── Margin ────────────────────────────────────────────────────────────────────
# Fallback if the live per-instrument lookup fails; assume the expensive rate.
MARGIN_RATE_FALLBACK = 0.05
# Require this multiple of the raw requirement to be free before entering. The
# pairs bot holds for ~29 days, so it is the account's continuous margin consumer;
# a modest buffer keeps it from taking the last dollar the MR bot needs.
MARGIN_SAFETY_FACTOR = float(os.environ.get('MARGIN_SAFETY_FACTOR', 1.15))

# DRY_RUN: compute and log/notify the decision but place NO orders. Use for an
# initial observation period before arming.
DRY_RUN    = os.environ.get('PAIRS_DRY_RUN', 'false').lower() == 'true'

# ── Timing ────────────────────────────────────────────────────────────────────
# The strategy is daily-cadence: decisions only fire on a new completed daily
# candle. We still wake hourly to reconcile broker state (detect a stop-out) and
# refresh HA sensors.
CHECK_INTERVAL_SECS = int(os.environ.get('PAIRS_CHECK_INTERVAL', '3600'))
DAILY_LOOKBACK      = 160   # completed daily candles to fetch (>= window + buffer)

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_DIR = os.environ.get('LOG_DIR', os.path.join(os.path.dirname(__file__), '..', 'logs'))
