"""
Time-stop policy simulator.

Same two-leg walk-forward as trade_simulator, but the holding cap is pluggable so
alternative policies can be compared on identical signals. Kept separate from
trade_simulator.py so the shipped daemon model stays untouched (mirrors
weekend_simulator.py / protection_simulator.py).

Policies
--------
none          no cap — legs run to TP or SL however long it takes
flat:<bars>   the live behaviour: one cap from fill, applied to both legs
post_tp1_free cap applies only while TP1 is unhit; once TP1 fires the runner is
              uncapped (its stop is already trailed to sl_after_tp1)
reset_at_tp1  the clock restarts when TP1 fires, giving the runner a fresh window
range:<k>     cap scaled by the setup's own entry range: bars = k x range_pips,
              clamped to [min_bars, max_bars]
"""

from dataclasses import dataclass
from typing import Optional

from signal_detector import Signal


def prepare(df):
    """Hoist the DataFrame -> numpy conversion out of the per-signal loop."""
    # Keep the DatetimeIndex itself (not .values) so searchsorted accepts the
    # pandas Timestamp on Signal.timestamp.
    return (df.index, df['high'].to_numpy(),
            df['low'].to_numpy(), df['close'].to_numpy())


@dataclass
class LegResult:
    direction:   str
    entry_price: float
    exit_price:  float
    exit_reason: str    # 'tp1' | 'tp2' | 'sl' | 'sl_after_tp1' | 'time_stop'
    pnl_points:  float


@dataclass
class TradeResult:
    signal:      Signal
    leg1:        Optional[LegResult] = None
    leg2:        Optional[LegResult] = None
    entry_range: float = 0.0
    bars_held:   int = 0
    tp1_hit:     bool = False
    capped:      bool = False   # did the time-stop actually bind?

    @property
    def total_pnl(self) -> float:
        # Size-weighted, matching trade_simulator and the v1.7.1 live fix: the two
        # legs are equal size, so the position result is their average, not their sum.
        legs = [leg.pnl_points for leg in (self.leg1, self.leg2) if leg]
        return sum(legs) / len(legs) if legs else 0.0

    @property
    def complete(self) -> bool:
        return self.leg1 is not None and self.leg2 is not None


def _cap_for(policy: str, entry_range_pips: float,
             min_bars: int, max_bars: int) -> Optional[int]:
    """Bars allowed from fill, or None for uncapped."""
    if policy == 'none' or policy == 'post_tp1_free':
        # post_tp1_free still needs its pre-TP1 cap; the caller passes that in
        # via flat_bars, so treat the base cap as unlimited here.
        return None
    if policy.startswith('flat:'):
        return int(policy.split(':')[1])
    if policy.startswith('range:'):
        k = float(policy.split(':')[1])
        return max(min_bars, min(max_bars, int(round(k * entry_range_pips))))
    if policy == 'reset_at_tp1':
        return None
    raise ValueError(f'unknown policy {policy!r}')


def simulate(signal: Signal, df, policy: str = 'flat:96',
             flat_bars: int = 96, pip_size: float = 0.0001,
             min_bars: int = 32, max_bars: int = 960,
             fill_window: int = 96, arrays=None) -> TradeResult:
    """arrays: optional (index, high, low, close) numpy tuple from prepare(df).

    The forward walk is bounded — fill_window bars to fill, then at most max_bars
    held — so an uncapped policy cannot scan to the end of a multi-year frame.
    Without the bound this is O(signals x frame) and a 5-year unfiltered run does
    not finish.
    """
    s = signal
    is_short = s.direction == 'short'
    entry_range = (s.r4 - s.p) if is_short else (s.p - s.s4)
    result = TradeResult(signal=signal, entry_range=entry_range)

    idx, highs, lows, closes = arrays if arrays is not None else prepare(df)
    start = int(idx.searchsorted(signal.timestamp, side='left'))
    stop = min(len(highs), start + fill_window + max_bars + 2)
    if start >= len(highs):
        return result

    range_pips = abs(entry_range) / pip_size
    base_cap = _cap_for(policy, range_pips, min_bars, max_bars)

    leg1_open = leg2_open = True
    leg2_sl = s.sl_initial
    filled = False
    bars_held = 0
    bars_waited = 0
    bars_since_tp1 = None

    for i in range(start, stop):
        h, l, c = highs[i], lows[i], closes[i]
        if not filled:
            if (is_short and h >= s.entry_price) or \
               (not is_short and l <= s.entry_price):
                filled = True
            else:
                bars_waited += 1
                if bars_waited >= fill_window:
                    break      # limit order would have expired unfilled
                continue
        bars_held += 1
        if bars_since_tp1 is not None:
            bars_since_tp1 += 1

        # Stops first — worst case within the bar.
        if is_short:
            if leg1_open and h >= s.sl_initial:
                result.leg1 = LegResult(s.direction, s.entry_price, s.sl_initial,
                                        'sl', s.entry_price - s.sl_initial)
                leg1_open = False
            if leg2_open and h >= leg2_sl:
                reason = 'sl_after_tp1' if result.tp1_hit else 'sl'
                result.leg2 = LegResult(s.direction, s.entry_price, leg2_sl,
                                        reason, s.entry_price - leg2_sl)
                leg2_open = False
            if leg1_open and l <= s.tp1:
                result.leg1 = LegResult(s.direction, s.entry_price, s.tp1,
                                        'tp1', s.entry_price - s.tp1)
                leg1_open = False
                leg2_sl = s.sl_after_tp1
                result.tp1_hit = True
                bars_since_tp1 = 0
            if leg2_open and l <= s.tp2:
                result.leg2 = LegResult(s.direction, s.entry_price, s.tp2,
                                        'tp2', s.entry_price - s.tp2)
                leg2_open = False
        else:
            if leg1_open and l <= s.sl_initial:
                result.leg1 = LegResult(s.direction, s.entry_price, s.sl_initial,
                                        'sl', s.sl_initial - s.entry_price)
                leg1_open = False
            if leg2_open and l <= leg2_sl:
                reason = 'sl_after_tp1' if result.tp1_hit else 'sl'
                result.leg2 = LegResult(s.direction, s.entry_price, leg2_sl,
                                        reason, leg2_sl - s.entry_price)
                leg2_open = False
            if leg1_open and h >= s.tp1:
                result.leg1 = LegResult(s.direction, s.entry_price, s.tp1,
                                        'tp1', s.tp1 - s.entry_price)
                leg1_open = False
                leg2_sl = s.sl_after_tp1
                result.tp1_hit = True
                bars_since_tp1 = 0
            if leg2_open and h >= s.tp2:
                result.leg2 = LegResult(s.direction, s.entry_price, s.tp2,
                                        'tp2', s.tp2 - s.entry_price)
                leg2_open = False

        if not leg1_open and not leg2_open:
            break

        # ── Time-stop ────────────────────────────────────────────────────────
        expired = False
        if policy == 'post_tp1_free':
            # Cap only bites while TP1 is unhit; after that the runner is free.
            expired = (not result.tp1_hit) and bars_held >= flat_bars
        elif policy == 'reset_at_tp1':
            expired = (bars_since_tp1 >= flat_bars) if result.tp1_hit \
                else (bars_held >= flat_bars)
        elif base_cap is not None:
            expired = bars_held >= base_cap

        if expired:
            close = c
            mtm = (s.entry_price - close) if is_short else (close - s.entry_price)
            if leg1_open:
                result.leg1 = LegResult(s.direction, s.entry_price, close,
                                        'time_stop', mtm)
                leg1_open = False
            if leg2_open:
                result.leg2 = LegResult(s.direction, s.entry_price, close,
                                        'time_stop', mtm)
                leg2_open = False
            result.capped = True
            break

    result.bars_held = bars_held
    return result
