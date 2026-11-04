"""Test harness for the Forex Pairs (EUR/GBP) add-on.

Nothing here may reach OANDA, Gmail or MQTT: dummy credentials, an HTTP layer
that refuses unstubbed calls, and e-mail recorded instead of sent.
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

os.environ.update({
    "OANDA_API_TOKEN": "test-token",
    "OANDA_ACCOUNT_ID": "000-000-0000000-000",
    "OANDA_ENV": "practice",
    "PAIRS_DRY_RUN": "false",
    "MQTT_HOST": "127.0.0.1",
    "LOG_DIR": tempfile.mkdtemp(prefix="forex-pairs-tests-"),
})
sys.path.insert(0, str(ROOT / "trader"))

import config  # noqa: E402
import logger  # noqa: E402
import notifier  # noqa: E402
import oanda_client  # noqa: E402
import requests  # noqa: E402
import state as state_mod  # noqa: E402

assert config.OANDA_BASE_URL == "https://api-fxpractice.oanda.com"


def config_in_subprocess(tmp_path, expr, env_overrides=None, drop=()):
    """Evaluate `config.<expr>` in a fresh process, as the add-on would see it.

    A no-op `dotenv` stub is put first on the path, so a developer's local .env
    can't leak a value (e.g. OANDA_ENV=live) into a test of the defaults.
    """
    import subprocess
    stub = tmp_path / "stub"
    stub.mkdir(exist_ok=True)
    (stub / "dotenv.py").write_text("def load_dotenv(*a, **k):\n    return False\n")
    env = {k: v for k, v in os.environ.items() if k not in drop}
    env.update(env_overrides or {})
    env["PYTHONPATH"] = str(stub)
    out = subprocess.run([sys.executable, "-c", f"import config; print(config.{expr})"],
                         cwd=ROOT / "trader", env=env, capture_output=True, text=True, check=True)
    return out.stdout.strip()


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_DIR", str(tmp_path))
    monkeypatch.setattr(state_mod, "LOG_DIR", str(tmp_path))
    monkeypatch.setattr(state_mod, "_STATE_FILE", str(tmp_path / "pairs_state.json"))
    for name in ("_JOURNAL", "_SUMMARY"):
        if hasattr(logger, name):
            monkeypatch.setattr(logger, name, str(tmp_path / f"{name.strip('_').lower()}"))

    def no_network(*a, **k):
        raise AssertionError("unstubbed HTTP call in a test")
    for verb in ("get", "post", "put"):
        monkeypatch.setattr(requests, verb, no_network)

    sent = []
    monkeypatch.setattr(notifier, "_send", lambda subject, body: sent.append(subject))
    monkeypatch.setattr(oanda_client, "_margin_rate", {})
    return sent


class FakeBroker:
    def __init__(self):
        self.calls = []
        self.trades = {}
        self.open_trades = []
        self.margin_ok = True
        self.fail = set()
        self.order_response = {"orderFillTransaction": {"price": "0.85210",
                                                        "tradeOpened": {"tradeID": "900"}}}

    def _rec(self, name, *args):
        self.calls.append((name, *args))
        if name in self.fail:
            raise RuntimeError(f"{name} failed (test)")

    def check_margin(self, instrument, units):
        self._rec("check_margin", instrument, units)
        return (self.margin_ok, 150.0, 1000.0 if self.margin_ok else 100.0)

    def place_market_order(self, direction, units, sl, instrument):
        self._rec("place_market_order", direction, units, sl, instrument)
        return self.order_response

    def get_open_trades(self, instrument=None):
        self._rec("get_open_trades", instrument)
        return self.open_trades

    def get_trade(self, trade_id):
        self._rec("get_trade", trade_id)
        return self.trades[trade_id]

    def close_trade(self, trade_id):
        self._rec("close_trade", trade_id)
        return {}

    def names(self):
        return [c[0] for c in self.calls]


@pytest.fixture
def broker(monkeypatch):
    b = FakeBroker()
    for name in ("check_margin", "place_market_order", "get_open_trades",
                 "get_trade", "close_trade"):
        monkeypatch.setattr(oanda_client, name, getattr(b, name))
    return b
