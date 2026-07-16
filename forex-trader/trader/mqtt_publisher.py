"""Non-blocking MQTT publisher — pushes forex trader state to Home Assistant."""

import json
import os
import time
import logging

log = logging.getLogger(__name__)

_client = None
_last_connect_attempt = 0.0
_RETRY_INTERVAL = 60  # seconds between reconnect attempts

_host = os.environ.get('MQTT_HOST', 'core-mosquitto')
_port = int(os.environ.get('MQTT_PORT', '1883'))
_user = os.environ.get('MQTT_USER', '')
_pass = os.environ.get('MQTT_PASSWORD', '')

TOPIC_ACCOUNT = 'forex_trader/account'
TOPIC_STATUS  = 'forex_trader/status'
TOPIC_CONN    = 'forex_trader/connection'


def _get_client():
    global _client, _last_connect_attempt

    # Return existing client without checking is_connected() — paho queues
    # messages during connection setup, so checking is_connected() here would
    # discard the client before the CONNACK arrives and silently drop publishes.
    if _client is not None:
        return _client

    now = time.time()
    if now - _last_connect_attempt < _RETRY_INTERVAL:
        return None
    _last_connect_attempt = now

    if not _host:
        return None

    try:
        import paho.mqtt.client as mqtt
        c = mqtt.Client(client_id='forex_trader_ha', clean_session=True)
        if _user:
            c.username_pw_set(_user, _pass)
        c.connect(_host, _port, keepalive=60)
        c.loop_start()
        _client = c
        log.info(f'MQTT connected to {_host}:{_port}')
        return _client
    except Exception as exc:
        log.warning(f'MQTT connect failed ({_host}:{_port}): {exc}')
        return None


def _publish(topic: str, payload: dict) -> None:
    c = _get_client()
    if c is None:
        return
    try:
        c.publish(topic, json.dumps(payload), qos=0, retain=True)
    except Exception as exc:
        log.warning(f'MQTT publish failed ({topic}): {exc}')
        global _client
        _client = None


def publish_status(state: dict) -> None:
    """Publish instrument status counts — reads in-memory state, no API call."""
    counts = {
        'active':  sum(1 for v in state.values() if v.get('status') == 'filled'),
        'pending': sum(1 for v in state.values() if v.get('status') == 'pending'),
        'idle':    sum(1 for v in state.values() if v.get('status') == 'idle'),
        'total':   len(state),
    }
    _publish(TOPIC_STATUS, counts)


def publish_account(account: dict) -> None:
    """Publish account summary (caller fetches from OANDA)."""
    payload = {
        'balance':        round(float(account.get('balance', 0)), 2),
        'NAV':            round(float(account.get('NAV', 0)), 2),
        'unrealizedPL':   round(float(account.get('unrealizedPL', 0)), 2),
        'openTradeCount': int(account.get('openTradeCount', 0)),
    }
    _publish(TOPIC_ACCOUNT, payload)


def publish_connection(ok: bool, health: dict) -> None:
    """Publish OANDA connection health so HA can alert on auth/connection loss.

    Retained topic: an HA MQTT binary_sensor can watch `connection_ok`, and a
    `seconds_since_success` staleness automation catches hangs the daemon itself
    can't self-report.
    """
    last = health.get('last_success')
    secs = health.get('seconds_since_success')
    payload = {
        'connection_ok':         bool(ok),
        'consecutive_failures':  int(health.get('consecutive_failures', 0)),
        'last_status':           health.get('last_status'),
        'last_error':            health.get('last_error'),
        'last_success':          last.isoformat() if last else None,
        'seconds_since_success': round(secs) if secs is not None else None,
    }
    _publish(TOPIC_CONN, payload)
