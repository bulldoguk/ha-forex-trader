"""The z-score rules, exactly as validated in the backtest."""
import math

import numpy as np
import pairs_strategy as ps
import pandas as pd
import pytest


def closes_with_z(target: float, n: int = ps.WINDOW) -> pd.Series:
    """n daily closes whose latest close sits at z = target (found by bisection)."""
    base = [0.85 * (1 + 0.002 * math.sin(i)) for i in range(n - 1)]

    def z_for(last):
        return ps.compute_z(pd.Series(base + [last]))[0]

    lo, hi = (0.80, 0.85) if target < z_for(0.85) else (0.85, 0.95)
    for _ in range(200):
        mid = (lo + hi) / 2
        if z_for(mid) < target:
            lo = mid
        else:
            hi = mid
    idx = pd.date_range("2026-01-01", periods=n, freq="D")
    s = pd.Series(base + [hi], index=idx)
    assert ps.compute_z(s)[0] == pytest.approx(target, abs=1e-3)
    return s


def test_needs_a_full_window():
    with pytest.raises(ValueError):
        ps.compute_z(pd.Series([0.85] * (ps.WINDOW - 1)))


def test_z_matches_the_formula():
    s = closes_with_z(1.3)
    lp = np.log(s)
    expected = (lp.iloc[-1] - lp.mean()) / lp.std(ddof=1)
    assert ps.compute_z(s)[0] == pytest.approx(expected)


@pytest.mark.parametrize("z, action, direction", [
    (2.05, "enter", "short"),     # stretched high → fade it
    (-2.05, "enter", "long"),     # stretched low → fade it
    (1.95, "hold", None),
    (-1.95, "hold", None),
])
def test_entry_rules_when_flat(z, action, direction):
    d = ps.decide(closes_with_z(z), in_position=False)
    assert d["action"] == action and d["direction"] == direction


def test_entry_sets_a_stop_on_the_far_side():
    short = ps.decide(closes_with_z(2.5), in_position=False)
    long = ps.decide(closes_with_z(-2.5), in_position=False)
    s = closes_with_z(2.5)
    assert short["stop"] > s.iloc[-1]           # short's stop is above the entry
    assert long["stop"] < closes_with_z(-2.5).iloc[-1]
    # and it sits exactly where z would reach the stop threshold
    assert math.log(short["stop"]) == pytest.approx(short["mu"] + ps.STOP_Z * short["sd"])


@pytest.mark.parametrize("z, action", [
    (0.4, "exit"),     # reverted
    (-0.4, "exit"),
    (1.0, "hold"),
    (-3.0, "hold"),
    (4.1, "exit"),     # blow-out
    (-4.1, "exit"),
])
def test_exit_rules_when_in_position(z, action):
    d = ps.decide(closes_with_z(z), in_position=True, direction="short")
    assert d["action"] == action


def test_never_enters_while_already_in_a_position():
    d = ps.decide(closes_with_z(3.0), in_position=True, direction="short")
    assert d["action"] != "enter"


def test_validated_parameters_are_unchanged():
    # Plateau-stable values from the stress test; changing them needs a new backtest.
    assert (ps.WINDOW, ps.ENTRY_Z, ps.EXIT_Z, ps.STOP_Z) == (60, 2.0, 0.5, 4.0)
