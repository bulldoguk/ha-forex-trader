"""Test harness for the Forex Trader add-on.

Safety first: nothing here may reach OANDA, Gmail or MQTT. Environment variables
are dummies, the HTTP layer refuses any call a test hasn't stubbed, and e-mail is
recorded instead of sent.
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Dummy credentials, set before any module reads them at import time.
os.environ.update({
    "OANDA_API_TOKEN": "test-token",
    "OANDA_ACCOUNT_ID": "000-000-0000000-000",
    "OANDA_ENV": "practice",
    "GMAIL_FROM_EMAIL": "bot@example.invalid",
    "GMAIL_APP_PASSWORD": "not-a-password",
    "NOTIFY_EMAIL": "owner@example.invalid",
    "MQTT_HOST": "127.0.0.1",
    "LOG_DIR": tempfile.mkdtemp(prefix="forex-trader-tests-"),
})
sys.path[:0] = [str(ROOT / "trader"), str(ROOT / "backtester")]

import config  # noqa: E402
import logger  # noqa: E402
import monitor  # noqa: E402,F401  (loaded here, under the dummy env)
import notifier  # noqa: E402
import oanda_client  # noqa: E402
import requests  # noqa: E402
import state as state_mod  # noqa: E402
import trader  # noqa: E402,F401  (loaded here, under the dummy env)

assert config.OANDA_BASE_URL == "https://api-fxpractice.oanda.com"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Per-test log dir, no network, no e-mail."""
    monkeypatch.setattr(config, "LOG_DIR", str(tmp_path))
    monkeypatch.setattr(state_mod, "LOG_DIR", str(tmp_path))
    monkeypatch.setattr(state_mod, "_STATE_FILE", str(tmp_path / "trader_state.json"))
    monkeypatch.setattr(logger, "_JOURNAL", str(tmp_path / "trades.jsonl"))
    monkeypatch.setattr(logger, "_SUMMARY", str(tmp_path / "trades_summary.csv"))

    def no_network(*a, **k):
        raise AssertionError("unstubbed HTTP call in a test")
    for verb in ("get", "post", "put"):
        monkeypatch.setattr(requests, verb, no_network)

    sent = []
    monkeypatch.setattr(notifier, "_send", lambda subject, body: sent.append(subject))
    monkeypatch.setattr(oanda_client, "_margin_rate_cache", {})
    return sent


class FakeBroker:
    """Stands in for oanda_client. Records every call that would touch the account."""

    def __init__(self):
        self.calls = []
        self.trades = {}
        self.orders = {}
        self.open_trades = []
        self.pending = []
        self.price = None
        self.margin_ok = True
        self.fail = set()          # method names that should raise
        self.fill = {"pl": "10.48", "price": None}

    def _rec(self, name, *args):
        self.calls.append((name, *args))
        if name in self.fail:
            raise RuntimeError(f"{name} failed (test)")

    def get_trade(self, trade_id):
        self._rec("get_trade", trade_id)
        return self.trades[trade_id]

    def get_order(self, order_id):
        self._rec("get_order", order_id)
        return self.orders[order_id]

    def get_current_price(self, instrument):
        self._rec("get_current_price", instrument)
        return self.price

    def get_open_trades(self, instrument=None):
        self._rec("get_open_trades", instrument)
        return self.open_trades

    def get_pending_orders(self, instrument=None):
        self._rec("get_pending_orders", instrument)
        return self.pending

    def check_margin(self, instrument, units):
        self._rec("check_margin", instrument, units)
        return self.margin_ok, 500.0, 1000.0 if self.margin_ok else 100.0

    def place_limit_order(self, direction, price, units, sl, instrument=None):
        self._rec("place_limit_order", direction, price, units, sl, instrument)
        return {"orderCreateTransaction": {"id": "501"}}

    def cancel_order(self, order_id):
        self._rec("cancel_order", order_id)
        return {}

    def partial_close(self, trade_id, units):
        self._rec("partial_close", trade_id, units)
        fill = {"pl": self.fill["pl"]}
        if self.fill["price"] is not None:
            fill["price"] = str(self.fill["price"])
        return {"orderFillTransaction": fill}

    def modify_sl(self, trade_id, sl):
        self._rec("modify_sl", trade_id, sl)
        return {}

    def close_trade(self, trade_id):
        self._rec("close_trade", trade_id)
        return {}

    def names(self):
        return [c[0] for c in self.calls]


@pytest.fixture
def broker(monkeypatch):
    b = FakeBroker()
    for name in ("get_trade", "get_order", "get_current_price", "get_open_trades",
                 "get_pending_orders", "check_margin", "place_limit_order",
                 "cancel_order", "partial_close", "modify_sl", "close_trade"):
        monkeypatch.setattr(oanda_client, name, getattr(b, name))
    return b


@pytest.fixture
def filled_long():
    """An open EURUSD long, TP1 not yet hit. Entry 1.1000, TP1 1.1030, TP2 1.1060."""
    return {
        **state_mod._EMPTY_INSTRUMENT,
        "status": "filled", "trade_id": "77", "order_id": "501",
        "direction": "long", "entry_price": 1.1000,
        "sl_initial": 1.0970, "sl_current": 1.0970, "sl_after_tp1": 1.1005,
        "tp1": 1.1030, "tp2": 1.1060, "entry_range": 41.0,
        "fill_time": None,
    }
