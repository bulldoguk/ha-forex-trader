"""Non-blocking MQTT publisher for the pairs bot — distinct topics from the MR
bot so both can drive separate Home Assistant sensors."""
import json, os, time, logging

log = logging.getLogger(__name__)

_client = None
_last_attempt = 0.0
_RETRY = 60

_host = os.environ.get('MQTT_HOST', 'core-mosquitto')
_port = int(os.environ.get('MQTT_PORT', '1883'))
_user = os.environ.get('MQTT_USER', '')
_pass = os.environ.get('MQTT_PASSWORD', '')

TOPIC_STATUS  = 'forex_pairs/status'
TOPIC_ACCOUNT = 'forex_pairs/account'


def _get_client():
    global _client, _last_attempt
    if _client is not None:
        return _client
    now = time.time()
    if now - _last_attempt < _RETRY or not _host:
        return None
    _last_attempt = now
    try:
        import paho.mqtt.client as mqtt
        c = mqtt.Client(client_id='forex_pairs_ha', clean_session=True)
        if _user:
            c.username_pw_set(_user, _pass)
        c.connect(_host, _port, keepalive=60)
        c.loop_start()
        _client = c
        log.info(f'MQTT connected {_host}:{_port}')
        return _client
    except Exception as exc:
        log.warning(f'MQTT connect failed: {exc}')
        return None


def _publish(topic, payload):
    c = _get_client()
    if c is None:
        return
    try:
        c.publish(topic, json.dumps(payload), qos=0, retain=True)
    except Exception as exc:
        global _client
        log.warning(f'MQTT publish failed ({topic}): {exc}')
        _client = None


def publish_status(state: dict, z: float | None = None):
    _publish(TOPIC_STATUS, {
        'status':       state.get('status', 'flat'),
        'direction':    state.get('direction'),
        'entry_price':  state.get('entry_price'),
        'entry_z':      state.get('entry_z'),
        'current_z':    round(z, 2) if z is not None else None,
    })


def publish_account(account: dict):
    _publish(TOPIC_ACCOUNT, {
        'balance':      round(float(account.get('balance', 0)), 2),
        'NAV':          round(float(account.get('NAV', 0)), 2),
        'unrealizedPL': round(float(account.get('unrealizedPL', 0)), 2),
    })
