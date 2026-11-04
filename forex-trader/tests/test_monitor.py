"""Position management: TP1 partial + stop move, TP2, time-stop, broker-side closes."""
import json
from datetime import datetime, timedelta, timezone

import config
import logger
import monitor
import pytest


def journal_closes():
    with open(logger._JOURNAL) as f:
        return [r for r in map(json.loads, f) if r["event"] == "trade_close"]


# ── Pure maths ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("entry, exit_, short, expected", [
    (1.1000, 1.1030, False, 30.0),    # long, price up: profit
    (1.1000, 1.0970, False, -30.0),   # long, price down: loss
    (1.1000, 1.0970, True, 30.0),     # short, price down: profit
    (1.1000, 1.1030, True, -30.0),    # short, price up: loss
])
def test_leg_pips_sign_follows_direction(entry, exit_, short, expected):
    assert monitor._leg_pips(entry, exit_, short, "EURUSD") == expected


def test_jpy_pair_uses_its_own_pip_size():
    assert monitor._leg_pips(190.00, 190.86, False, "GBPJPY") == 86.0


def test_runner_close_price_backs_tp1_leg_out_of_the_average():
    # EURUSD: 5,000 closed at TP1 1.1030, 5,000 runner closed at 1.1010.
    st = {"tp1_hit": True, "tp1_price_actual": 1.1030}
    avg = (1.1030 * 5000 + 1.1010 * 5000) / 10000
    assert monitor._runner_close_price(st, avg, "EURUSD") == pytest.approx(1.1010)


def test_runner_close_price_untouched_before_tp1():
    assert monitor._runner_close_price({"tp1_hit": False}, 1.0990, "EURUSD") == 1.0990


def test_trade_pnl_is_size_weighted_not_summed():
    # A stop-loss exit moves both legs the same distance: the position lost 43.2
    # pips, not 86.4 (the v1.7.1 double-count bug).
    st = {"direction": "long", "entry_price": 1.1, "tp1": 1.2, "tp2": 1.3,
          "sl_initial": 1.0, "entry_range": 41.0}
    total = logger.log_trade_close(st, "EURUSD", 1.0957, "CLOSED", -43.2, -43.2, 5000, 5000)
    assert total == pytest.approx(-43.2)


# ── check_and_act ─────────────────────────────────────────────────────────────

def test_holds_when_no_target_reached(broker, filled_long):
    broker.trades["77"] = {"state": "OPEN"}
    broker.price = 1.1010
    event, st = monitor.check_and_act(filled_long, "EURUSD")
    assert event == "open"
    assert not {"partial_close", "modify_sl", "close_trade"} & set(broker.names())


def test_tp1_takes_partial_and_moves_stop(broker, filled_long, isolated):
    broker.trades["77"] = {"state": "OPEN"}
    broker.price = 1.1031
    broker.fill["price"] = 1.1029          # filled a pip worse than the polled price
    event, st = monitor.check_and_act(filled_long, "EURUSD")

    assert event == "tp1_hit"
    assert ("partial_close", "77", config.INSTRUMENTS["EURUSD"]["units_partial"]) in broker.calls
    assert ("modify_sl", "77", 1.1005) in broker.calls
    assert st["tp1_hit"] is True
    assert st["sl_current"] == 1.1005
    assert st["leg1_pips"] == 29.0          # measured from the real fill, not 31
    assert st["tp1_realized_pl"] == pytest.approx(10.48)
    assert isolated, "a TP1 notification should be sent"


def test_tp1_for_a_short_triggers_on_price_falling(broker, filled_long):
    st = {**filled_long, "direction": "short", "entry_price": 1.1000,
          "tp1": 1.0970, "tp2": 1.0940, "sl_after_tp1": 1.0995}
    broker.trades["77"] = {"state": "OPEN"}
    broker.price = 1.0969
    event, _ = monitor.check_and_act(st, "EURUSD")
    assert event == "tp1_hit"


def test_tp1_failure_leaves_state_alone_and_alerts(broker, filled_long, isolated):
    broker.trades["77"] = {"state": "OPEN"}
    broker.price = 1.1031
    broker.fail.add("partial_close")
    before = dict(filled_long)

    event, st = monitor.check_and_act(filled_long, "EURUSD")

    assert event == "error"
    assert st == before                     # not marked tp1_hit
    assert "modify_sl" not in broker.names()
    assert any("ERROR" in s.upper() for s in isolated)


def test_tp2_closes_the_runner(broker, filled_long):
    st = {**filled_long, "tp1_hit": True, "leg1_pips": 30.0, "sl_current": 1.1005}
    broker.trades["77"] = {"state": "OPEN"}
    broker.price = 1.1061
    event, new_st = monitor.check_and_act(st, "EURUSD")
    assert event == "closed" and new_st is None
    assert ("close_trade", "77") in broker.calls
    (rec,) = journal_closes()
    assert rec["close_reason"] == "tp2"
    assert rec["total_pnl_pips"] == pytest.approx((30.0 + 61.0) / 2)


def test_time_stop_force_closes_after_max_hold(broker, filled_long):
    filled_long["fill_time"] = str(datetime.now(timezone.utc)
                                   - timedelta(hours=config.MAX_HOLD_HOURS + 1))
    broker.trades["77"] = {"state": "OPEN"}
    broker.price = 1.0990
    event, _ = monitor.check_and_act(filled_long, "EURUSD")
    assert event == "closed"
    assert ("close_trade", "77") in broker.calls
    assert journal_closes()[0]["close_reason"] == "time_stop"


def test_time_stop_retries_when_the_close_fails(broker, filled_long):
    filled_long["fill_time"] = str(datetime.now(timezone.utc)
                                   - timedelta(hours=config.MAX_HOLD_HOURS + 1))
    broker.trades["77"] = {"state": "OPEN"}
    broker.price = 1.0990
    broker.fail.add("close_trade")
    event, st = monitor.check_and_act(filled_long, "EURUSD")
    assert event == "open" and st is filled_long     # still tracked, retried next cycle


def test_broker_side_close_is_journaled(broker, filled_long):
    broker.trades["77"] = {"state": "CLOSED", "averageClosePrice": "1.0970"}
    event, _ = monitor.check_and_act(filled_long, "EURUSD")
    assert event == "closed"
    (rec,) = journal_closes()
    assert rec["total_pnl_pips"] == pytest.approx(-30.0)
    assert not {"close_trade", "partial_close"} & set(broker.names())


def test_lookup_failure_does_nothing(broker, filled_long):
    broker.fail.add("get_trade")
    event, st = monitor.check_and_act(filled_long, "EURUSD")
    assert event == "error" and st is filled_long
    assert broker.names() == ["get_trade"]
