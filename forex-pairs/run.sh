#!/usr/bin/with-contenv bashio

# ── Credentials from HA add-on options (SAME OANDA account as the MR bot) ──────
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

# ── Strategy tunables ─────────────────────────────────────────────────────────
export EURGBP_UNITS=$(bashio::config 'eurgbp_units')
export PAIRS_DRY_RUN=$(bashio::config 'dry_run')
export MARGIN_SAFETY_FACTOR=$(bashio::config 'margin_safety_factor')
export PAIRS_CHECK_OFFSET_MINS=$(bashio::config 'check_offset_mins')

# ── Persistent storage (separate dir from the MR bot) ─────────────────────────
export LOG_DIR=/share/forex_pairs/logs
mkdir -p "${LOG_DIR}"

export PYTHONUNBUFFERED=1

bashio::log.info "Starting Forex Pairs (EUR/GBP) — OANDA ${OANDA_ENV}, dry_run=${PAIRS_DRY_RUN}, units=${EURGBP_UNITS}"

exec python3 /app/entrypoint.py
