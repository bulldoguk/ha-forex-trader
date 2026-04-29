#!/usr/bin/with-contenv bashio

# ── Read credentials from HA add-on options ───────────────────────────────────
export OANDA_API_TOKEN=$(bashio::config 'oanda_token')
export OANDA_ACCOUNT_ID=$(bashio::config 'oanda_account_id')
export OANDA_ENV=$(bashio::config 'oanda_env')
export GMAIL_FROM_EMAIL=$(bashio::config 'gmail_from')
export GMAIL_APP_PASSWORD=$(bashio::config 'gmail_app_password')
export NOTIFY_EMAIL=$(bashio::config 'notify_email')

# ── Per-instrument toggles and sizing ─────────────────────────────────────────
export GBPUSD_ENABLED=$(bashio::config 'gbpusd_enabled')
export EURUSD_ENABLED=$(bashio::config 'eurusd_enabled')
export GOLD_ENABLED=$(bashio::config 'gold_enabled')
export GBPUSD_UNITS=$(bashio::config 'gbpusd_units')
export EURUSD_UNITS=$(bashio::config 'eurusd_units')
export GOLD_UNITS=$(bashio::config 'gold_units')

# ── Persistent storage (survives container restarts) ──────────────────────────
export LOG_DIR=/share/forex_trader/logs
mkdir -p "${LOG_DIR}"

bashio::log.info "Starting Forex Trader — OANDA ${OANDA_ENV}"
bashio::log.info "Instruments: GBPUSD=${GBPUSD_ENABLED} EURUSD=${EURUSD_ENABLED} GOLD=${GOLD_ENABLED}"

exec python3 /app/entrypoint.py
