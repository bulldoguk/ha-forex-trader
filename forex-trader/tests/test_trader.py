"""Order lifecycle: idle → pending → filled, and every way a pending order can end."""
from types import SimpleNamespace

import config
import pytest
import scanner
import state as state_mod
import trader


@pytest.fixture
def idle_state():
    return state_mod._empty_state()


@pytest.fixture
def signal(monkeypatch):
    sig = SimpleNamespace(direction="short", entry_price=1.1040, p=1.1000,
                          sl_initial=1.1080, sl_after_tp1=1.1035,
                          tp1=1.1020, tp2=1.1000)
    monkeypatch.setattr(scanner, "latest_signal", lambda key: sig)
    return sig


def test_signal_places_one_limit_order_with_a_stop(broker, idle_state, signal):
    state = trader._handle_idle(idle_state, "EURUSD")

    orders = [c for c in broker.calls if c[0] == "place_limit_order"]
    assert orders == [("place_limit_order", "short", 1.1040,
                       config.INSTRUMENTS["EURUSD"]["units_total"], 1.1080, "EUR_USD")]
    st = state["EURUSD"]
    assert st["status"] == "pending" and st["order_id"] == "501"
    assert st["sl_initial"] == 1.1080
    assert state_mod.load()["EURUSD"]["status"] == "pending"     # persisted


def test_no_order_when_position_limit_reached(broker, idle_state, signal):
    idle_state["GBPUSD"]["status"] = "filled"
    assert config.MAX_CONCURRENT_POSITIONS == 1
    trader._handle_idle(idle_state, "EURUSD")
    assert broker.calls == []


def test_no_order_when_margin_is_short(broker, idle_state, signal):
    broker.margin_ok = False
    state = trader._handle_idle(idle_state, "EURUSD")
    assert "place_limit_order" not in broker.names()
    assert state["EURUSD"]["status"] == "idle"


def test_no_order_without_a_signal(broker, idle_state, monkeypatch):
    monkeypatch.setattr(scanner, "latest_signal", lambda key: None)
    trader._handle_idle(idle_state, "EURUSD")
    assert broker.calls == []


def test_failed_order_stays_idle(broker, idle_state, signal):
    broker.fail.add("place_limit_order")
    state = trader._handle_idle(idle_state, "EURUSD")
    assert state["EURUSD"]["status"] == "idle"


@pytest.fixture
def pending_state(idle_state):
    idle_state["EURUSD"].update(status="pending", order_id="501", direction="short",
                                entry_price=1.1040, sl_initial=1.1080,
                                sl_after_tp1=1.1035, tp1=1.1020, tp2=1.1000)
    return idle_state


def test_fill_records_the_real_fill_price(broker, pending_state):
    broker.open_trades = [{"id": "77", "price": "1.1046"}]
    state = trader._handle_pending(pending_state, "EURUSD")
    st = state["EURUSD"]
    assert st["status"] == "filled" and st["trade_id"] == "77"
    assert st["entry_price"] == 1.1046                       # slippage kept


def test_still_pending_inside_ttl_does_nothing(broker, pending_state):
    broker.pending = [{"id": "501"}]
    state = trader._handle_pending(pending_state, "EURUSD")
    assert state["EURUSD"]["status"] == "pending"
    assert "cancel_order" not in broker.names()


def test_ttl_expiry_cancels_and_resets(broker, pending_state):
    broker.pending = [{"id": "501"}]
    pending_state["EURUSD"]["bars_since_signal"] = config.LIMIT_ORDER_TTL - 1
    state = trader._handle_pending(pending_state, "EURUSD")
    assert ("cancel_order", "501") in broker.calls
    assert state["EURUSD"]["status"] == "idle"


def test_broker_cancelled_order_resets_without_a_trade(broker, pending_state):
    broker.orders["501"] = {"state": "CANCELLED", "cancellingTransactionID": "82"}
    state = trader._handle_pending(pending_state, "EURUSD")
    assert state["EURUSD"]["status"] == "idle"


def test_order_that_filled_and_closed_between_scans_is_journaled(broker, pending_state):
    broker.orders["501"] = {"state": "FILLED", "tradeOpenedID": "77"}
    broker.trades["77"] = {"state": "CLOSED", "price": "1.1041",
                           "averageClosePrice": "1.1080", "realizedPL": "-19.5",
                           "openTime": "2026-07-30T10:46:00Z"}
    state = trader._handle_pending(pending_state, "EURUSD")
    assert state["EURUSD"]["status"] == "idle"
    import logger, json
    with open(logger._JOURNAL) as f:
        closes = [r for r in map(json.loads, f) if r["event"] == "trade_close"]
    assert len(closes) == 1 and closes[0]["total_pnl_pips"] == pytest.approx(-39.0)


def test_order_filled_and_still_open_is_adopted(broker, pending_state):
    broker.orders["501"] = {"state": "FILLED", "tradeOpenedID": "77"}
    broker.trades["77"] = {"state": "OPEN", "price": "1.1041"}
    state = trader._handle_pending(pending_state, "EURUSD")
    assert state["EURUSD"]["status"] == "filled"
    assert state["EURUSD"]["trade_id"] == "77"


def test_order_lookup_failure_changes_nothing(broker, pending_state):
    broker.fail.add("get_order")
    before = dict(pending_state["EURUSD"])
    state = trader._handle_pending(pending_state, "EURUSD")
    after = dict(state["EURUSD"])
    assert after.pop("bars_since_signal") == 1
    before.pop("bars_since_signal")
    assert after == before


def test_closed_position_resets_instrument(broker, idle_state, filled_long):
    idle_state["EURUSD"] = filled_long
    broker.trades["77"] = {"state": "CLOSED", "averageClosePrice": "1.0970"}
    state = trader._handle_filled(idle_state, "EURUSD")
    assert state["EURUSD"]["status"] == "idle"
    assert state_mod.load()["EURUSD"]["status"] == "idle"
