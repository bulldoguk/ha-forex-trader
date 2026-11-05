"""Persisted daemon state survives restarts and picks up newly added instruments."""
import json

import config
import scanner
import state as state_mod


def test_fresh_state_is_all_idle():
    st = state_mod.load()
    assert set(st) == set(config.INSTRUMENTS)
    assert all(v["status"] == "idle" for v in st.values())


def test_round_trip_and_new_instruments_are_added():
    saved = {"EURUSD": {**state_mod._EMPTY_INSTRUMENT, "status": "filled", "trade_id": "77"}}
    with open(state_mod._STATE_FILE, "w") as f:
        json.dump(saved, f)
    st = state_mod.load()
    assert st["EURUSD"]["trade_id"] == "77"
    assert st["GBPUSD"]["status"] == "idle"


def test_reset_instrument_clears_only_that_one():
    st = state_mod._empty_state()
    st["EURUSD"]["status"] = "filled"
    st["GBPUSD"]["status"] = "pending"
    state_mod.reset_instrument(st, "EURUSD")
    loaded = state_mod.load()
    assert loaded["EURUSD"]["status"] == "idle"
    assert loaded["GBPUSD"]["status"] == "pending"


def test_reset_does_not_share_the_template_dict():
    st = state_mod._empty_state()
    st["EURUSD"]["status"] = "filled"
    assert state_mod._EMPTY_INSTRUMENT["status"] == "idle"
    assert st["GBPUSD"]["status"] == "idle"


def test_pips_are_unsigned_and_per_instrument():
    assert scanner.pips(-0.0041, "GBPUSD") == 41.0
    assert scanner.pips(0.86, "GBPJPY") == 86.0


def test_every_instrument_trades_a_half_and_half_split():
    for key, cfg in config.INSTRUMENTS.items():
        assert cfg["units_partial"] * 2 == cfg["units_total"], key
        assert cfg["oanda"].replace("_", "") == key


def test_code_version_matches_the_add_on_manifest():
    import re
    from pathlib import Path
    import monitor
    manifest = (Path(__file__).resolve().parents[1] / "config.yaml").read_text()
    assert re.search(r'^version: "([^"]+)"', manifest, re.M).group(1) == monitor.VERSION
