"""The broker client: what goes on the wire, margin checks, retries and health."""
import os
import subprocess
import sys
from pathlib import Path

import config
import oanda_client as oa
import pytest
import requests


@pytest.fixture
def posted(monkeypatch):
    sent = []
    monkeypatch.setattr(oa, "_post", lambda path, body: sent.append((path, body)) or {})
    monkeypatch.setattr(oa, "_put", lambda path, body: sent.append((path, body)) or {})
    return sent


def test_short_limit_order_is_negative_units_with_stop_on_fill(posted):
    oa.place_limit_order("short", 1.10405, 10_000, 1.10812, instrument="EUR_USD")
    (path, body) = posted[0]
    assert path.endswith("/orders")
    o = body["order"]
    assert o["type"] == "LIMIT" and o["instrument"] == "EUR_USD"
    assert o["units"] == "-10000"
    assert o["price"] == "1.10405"
    assert o["stopLossOnFill"] == {"price": "1.10812", "timeInForce": "GTC"}


def test_long_limit_order_is_positive_units_and_jpy_prices_use_3dp(posted):
    oa.place_limit_order("long", 190.123456, 8_000, 189.5, instrument="GBP_JPY")
    o = posted[0][1]["order"]
    assert o["units"] == "8000"
    assert o["price"] == "190.123" and o["stopLossOnFill"]["price"] == "189.500"


def test_partial_close_sends_units_and_full_close_sends_none(posted):
    oa.partial_close("77", 5000)
    oa.close_trade("77")
    assert posted[0] == (f"/v3/accounts/{config.OANDA_ACCOUNT}/trades/77/close", {"units": "5000"})
    assert posted[1][1] == {}


def test_margin_check_applies_safety_factor(monkeypatch):
    monkeypatch.setattr(oa, "get_margin_rate", lambda i: 0.02)
    monkeypatch.setattr(oa, "get_account_summary", lambda: {"marginAvailable": "250"})
    # 10,000 USD_CAD at 2% = $200; x1.25 = $250 → exactly affordable
    assert oa.check_margin("USD_CAD", 10_000) == (True, 200.0, 250.0)
    monkeypatch.setattr(oa, "get_account_summary", lambda: {"marginAvailable": "249"})
    assert oa.check_margin("USD_CAD", 10_000)[0] is False


def test_margin_check_refuses_when_unknown(monkeypatch):
    def boom():
        raise RuntimeError("down")
    monkeypatch.setattr(oa, "get_margin_rate", lambda i: 0.02)
    monkeypatch.setattr(oa, "get_account_summary", boom)
    assert oa.check_margin("USD_CAD", 10_000) == (False, 0.0, 0.0)


def test_unknown_instrument_margin_rate_falls_back_to_the_expensive_rate(monkeypatch):
    monkeypatch.setattr(oa, "_get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError()))
    assert oa.get_margin_rate("NZD_USD") == config.MARGIN_RATE_FALLBACK == 0.05


class Resp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"{self.status_code}")


@pytest.fixture
def wire(monkeypatch):
    """Scripted responses for requests.get; sleeps are skipped."""
    script = []
    monkeypatch.setattr(oa.time, "sleep", lambda s: None)

    def fake_get(url, **kw):
        assert url.startswith("https://api-fxpractice.oanda.com")
        assert kw["headers"]["Authorization"] == "Bearer test-token"
        item = script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item
    monkeypatch.setattr(requests, "get", fake_get)
    oa._health.update(consecutive_failures=0, last_success=None)
    return script


def test_retries_5xx_then_succeeds(wire):
    wire += [Resp(503), Resp(502), Resp(200, {"ok": 1})]
    assert oa._get("/x") == {"ok": 1}
    assert oa.get_health()["consecutive_failures"] == 0


def test_401_gets_two_quick_retries_then_raises_and_counts(wire):
    wire += [Resp(401), Resp(401), Resp(401)]
    with pytest.raises(requests.exceptions.HTTPError):
        oa._get("/x")
    assert wire == []
    assert oa.get_health()["consecutive_failures"] == 1
    assert oa.get_health()["last_status"] == 401


def test_transport_errors_exhaust_retries_then_raise(wire):
    wire += [requests.exceptions.ConnectionError()] * 4
    with pytest.raises(requests.exceptions.ConnectionError):
        oa._get("/x")
    assert oa.get_health()["consecutive_failures"] == 1


def test_400_is_not_retried(wire):
    wire += [Resp(400), Resp(200)]
    with pytest.raises(requests.exceptions.HTTPError):
        oa._get("/x")
    assert len(wire) == 1


@pytest.mark.parametrize("env, url", [
    (None, "https://api-fxpractice.oanda.com"),
    ("practice", "https://api-fxpractice.oanda.com"),
    ("LIVE", "https://api-fxpractice.oanda.com"),   # only exactly "live" goes live
    ("live", "https://api-fxtrade.oanda.com"),
])
def test_only_an_explicit_live_setting_reaches_the_live_api(env, url):
    trader_dir = Path(__file__).resolve().parents[1] / "trader"
    e = {k: v for k, v in os.environ.items() if k != "OANDA_ENV"}
    if env is not None:
        e["OANDA_ENV"] = env
    out = subprocess.run([sys.executable, "-c", "import config; print(config.OANDA_BASE_URL)"],
                         cwd=trader_dir, env=e, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == url
