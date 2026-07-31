#!/usr/bin/with-contenv bashio

# ── Read credentials from HA add-on options ───────────────────────────────────
export OANDA_API_TOKEN=$(bashio::config 'oanda_token')
export OANDA_ACCOUNT_ID=$(bashio::config 'oanda_account_id')
export OANDA_ENV=$(bashio::config 'oanda_env')
export GMAIL_FROM_EMAIL=$(bashio::config 'gmail_from')
export GMAIL_APP_PASSWORD=$(bashio::config 'gmail_app_password')
export NOTIFY_EMAIL=$(bashio::config 'notify_email')
export MQTT_HOST=$(bashio::config 'mqtt_host')
export MQTT_PORT=$(bashio::config 'mqtt_port')
export MQTT_USER=$(bashio::config 'mqtt_user')
export MQTT_PASSWORD=$(bashio::config 'mqtt_password')

# ── Per-instrument toggles and sizing ─────────────────────────────────────────
export GBPUSD_ENABLED=$(bashio::config 'gbpusd_enabled')
export EURUSD_ENABLED=$(bashio::config 'eurusd_enabled')
export GBPJPY_ENABLED=$(bashio::config 'gbpjpy_enabled')
export USDCAD_ENABLED=$(bashio::config 'usdcad_enabled')
export GBPUSD_UNITS=$(bashio::config 'gbpusd_units')
export EURUSD_UNITS=$(bashio::config 'eurusd_units')
export GBPJPY_UNITS=$(bashio::config 'gbpjpy_units')
export USDCAD_UNITS=$(bashio::config 'usdcad_units')

# ── Margin budget (see decisions/0003-margin-budget-small-account.md) ─────────
export MAX_CONCURRENT_POSITIONS=$(bashio::config 'max_concurrent_positions')
export MARGIN_SAFETY_FACTOR=$(bashio::config 'margin_safety_factor')

# ── Holding-time cap (see docs/research_timestop_tuning.md, ADR-0002) ─────────
export MAX_HOLD_HOURS=$(bashio::config 'max_hold_hours')

# ── Persistent storage (survives container restarts) ──────────────────────────
export LOG_DIR=/share/forex_trader/logs
mkdir -p "${LOG_DIR}"

bashio::log.info "Starting Forex Trader — OANDA ${OANDA_ENV}"
bashio::log.info "Instruments: GBPUSD=${GBPUSD_ENABLED} EURUSD=${EURUSD_ENABLED} GBPJPY=${GBPJPY_ENABLED} USDCAD=${USDCAD_ENABLED}"
bashio::log.info "Margin budget: max_concurrent=${MAX_CONCURRENT_POSITIONS} safety_factor=${MARGIN_SAFETY_FACTOR}"
bashio::log.info "Time-stop: max_hold_hours=${MAX_HOLD_HOURS}"

# Force Python to flush stdout immediately — without this, print() output
# is buffered in Docker and never appears in the HA log viewer
export PYTHONUNBUFFERED=1

exec python3 /app/entrypoint.py
