"""Entering, exiting and reconciling the single EUR/GBP position."""
import json
import os
import subprocess
import sys
from pathlib import Path

import config
import logger
import oanda_client as oa
import pairs_trader as pt
import pytest
import state as state_mod
from test_strategy import closes_with_z


def closes_logged():
    path = logger._JOURNAL
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [r for r in map(json.loads, f) if r["event"] == "trade_close"]


@pytest.fixture
def flat():
    return state_mod.load()


@pytest.fixture
def holding_short(flat):
    flat.update(status="in_position", trade_id="900", direction="short",
                entry_price=0.8600, units=config.UNITS, stop_price=0.8800,
                last_daily_date="2026-02-28")
    return flat


@pytest.mark.parametrize("entry, close, direction, pips", [
    (0.8600, 0.8550, "short", 50.0),
    (0.8600, 0.8650, "short", -50.0),
    (0.8600, 0.8650, "long", 50.0),
])
def test_pips_sign(entry, close, direction, pips):
    assert pt._pips(entry, close, direction) == pytest.approx(pips)


def test_entry_places_a_market_order_with_a_stop(broker, flat):
    st = pt.act_on_new_bar(flat, closes_with_z(2.3))
    (order,) = [c for c in broker.calls if c[0] == "place_market_order"]
    _, direction, units, stop, instrument = order
    assert (direction, units, instrument) == ("short", config.UNITS, "EUR_GBP")
    assert stop > 0.85
    assert st["status"] == "in_position" and st["trade_id"] == "900"
    assert st["entry_price"] == 0.8521
    assert state_mod.load()["status"] == "in_position"


def test_no_entry_when_margin_is_short(broker, flat):
    broker.margin_ok = False
    st = pt.act_on_new_bar(flat, closes_with_z(2.3))
    assert "place_market_order" not in broker.names()
    assert st["status"] == "flat"


def test_unfilled_order_stays_flat_and_alerts(broker, flat, isolated):
    broker.order_response = {"orderCancelTransaction": {"reason": "MARKET_HALTED"}}
    st = pt.act_on_new_bar(flat, closes_with_z(2.3))
    assert st["status"] == "flat"
    assert isolated, "an error e-mail should be sent"


def test_dry_run_never_trades(broker, flat, monkeypatch):
    monkeypatch.setattr(config, "DRY_RUN", True)
    pt.act_on_new_bar(flat, closes_with_z(2.3))
    assert broker.calls == []


def test_reversion_closes_and_keeps_last_bar(broker, holding_short):
    broker.trades["900"] = {"averageClosePrice": "0.8550", "realizedPL": "16.0"}
    s = closes_with_z(0.2)
    st = pt.act_on_new_bar(holding_short, s)
    assert ("close_trade", "900") in broker.calls
    assert st["status"] == "flat"
    assert st["last_daily_date"] == s.index[-1].date().isoformat()
    (rec,) = closes_logged()
    assert rec["pnl_pips"] == pytest.approx(50.0)


def test_failed_close_keeps_the_position(broker, holding_short):
    broker.fail.add("close_trade")
    st = pt.act_on_new_bar(holding_short, closes_with_z(0.2))
    assert st["status"] == "in_position" and st["trade_id"] == "900"
    assert closes_logged() == []


def test_reconcile_settles_a_stopped_out_position(broker, holding_short):
    broker.open_trades = []
    broker.trades["900"] = {"averageClosePrice": "0.8800", "realizedPL": "-52.0"}
    st = pt.reconcile(holding_short)
    assert st["status"] == "flat"
    assert st["last_daily_date"] == "2026-02-28"      # won't re-trade the same bar
    (rec,) = closes_logged()
    assert rec["close_reason"] == "stop_or_manual"
    assert rec["pnl_pips"] == pytest.approx(-200.0)


def test_reconcile_leaves_an_open_position_alone(broker, holding_short):
    broker.open_trades = [{"id": "900"}]
    st = pt.reconcile(holding_short)
    assert st["status"] == "in_position"
    assert "get_trade" not in broker.names()


def test_market_order_body(monkeypatch):
    sent = []
    monkeypatch.setattr(oa, "_post", lambda path, body: sent.append(body) or {})
    oa.place_market_order("short", 2600, 0.87123456, "EUR_GBP")
    o = sent[0]["order"]
    assert o["type"] == "MARKET" and o["timeInForce"] == "FOK"
    assert o["units"] == "-2600"
    assert o["stopLossOnFill"] == {"price": "0.87123", "timeInForce": "GTC"}


def test_margin_check_refuses_when_unknown(monkeypatch):
    monkeypatch.setattr(oa, "get_account_summary",
                        lambda: (_ for _ in ()).throw(RuntimeError("down")))
    assert oa.check_margin("EUR_GBP", 2600)[0] is False


@pytest.mark.parametrize("env, url", [
    (None, "https://api-fxpractice.oanda.com"),
    ("LIVE", "https://api-fxpractice.oanda.com"),
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


def test_dry_run_is_off_unless_asked_for():
    assert config.DRY_RUN is False
