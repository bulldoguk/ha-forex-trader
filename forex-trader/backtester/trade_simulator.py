"""
Simulates the two-leg trade for a given signal, walking forward
through subsequent M15 candles until both legs are closed.
"""

import pandas as pd
from dataclasses import dataclass, field
from typing import Optional
from signal_detector import Signal
from config import MAX_HOLD_BARS


@dataclass
class LegResult:
    direction:   str
    entry_price: float
    exit_price:  float
    exit_reason: str    # 'tp1', 'tp2', 'sl'
    pnl_points:  float  # in price units (not pips)


@dataclass
class TradeResult:
    signal:    Signal
    leg1:      Optional[LegResult] = None
    leg2:      Optional[LegResult] = None
    entry_range: float = 0.0   # distance R8/S0 → P4 at entry (context for filter analysis)

    @property
    def total_pnl(self) -> float:
        # Size-weighted position P&L. The two legs are equal size (NUM_LEGS=2), so
        # the position result is their average, not their sum. Summing double-counts
        # (both SL-only legs move the same distance → 2× the real figure) and mirrors
        # the live-daemon pip bug fixed in v1.7.1. pnl_points are per-unit price
        # moves; weighting keeps backtest expectancy on the same scale as live P&L.
        legs = [leg.pnl_points for leg in (self.leg1, self.leg2) if leg]
        return sum(legs) / len(legs) if legs else 0.0

    @property
    def outcome(self) -> str:
        if not self.leg1 or not self.leg2:
            return 'incomplete'
        reasons = {self.leg1.exit_reason, self.leg2.exit_reason}
        if 'tp2' in reasons:
            return 'full_win' if self.leg1.exit_reason == 'tp1' else 'partial_win'
        if self.leg1.exit_reason == 'tp1':
            return 'tp1_only'
        if 'time_stop' in reasons:
            return 'timeout'   # hit the hold cap before TP or SL
        return 'loss'


def simulate(signal: Signal, df: pd.DataFrame,
             max_hold_bars: int = MAX_HOLD_BARS) -> TradeResult:
    """
    df is the full M15+pivot DataFrame. We walk forward from signal.timestamp.

    max_hold_bars caps how many M15 bars a position may stay open after fill,
    mirroring the live daemon's time-stop (config.MAX_HOLD_HOURS). Any leg still
    open at the cap is marked-to-market at that bar's close. Pass a large value
    (or None) only to reproduce the legacy unlimited-hold behaviour.
    """
    future = df[df.index >= signal.timestamp]
    if future.empty:
        return TradeResult(signal=signal)

    s = signal
    is_short = s.direction == 'short'
    result = TradeResult(
        signal=signal,
        entry_range=s.r4 - s.p if is_short else s.p - s.s4,
    )

    leg1_open = True
    leg2_open = True
    leg2_sl   = s.sl_initial
    filled    = False  # limit order not yet filled
    bars_held = 0      # M15 bars since fill (for the time-stop)

    for _, bar in future.iterrows():
        # Wait for price to touch the entry level (limit order fill)
        if not filled:
            if is_short and bar['high'] >= s.entry_price:
                filled = True
            elif not is_short and bar['low'] <= s.entry_price:
                filled = True
            else:
                continue
        bars_held += 1
        h, l = bar['high'], bar['low']

        if is_short:
            # Check SL first (worst case within bar)
            if leg1_open and h >= s.sl_initial:
                result.leg1 = LegResult(s.direction, s.entry_price, s.sl_initial,
                                        'sl', s.entry_price - s.sl_initial)
                leg1_open = False
            if leg2_open and h >= leg2_sl:
                result.leg2 = LegResult(s.direction, s.entry_price, leg2_sl,
                                        'sl', s.entry_price - leg2_sl)
                leg2_open = False

            # TP1 (leg 1 target)
            if leg1_open and l <= s.tp1:
                result.leg1 = LegResult(s.direction, s.entry_price, s.tp1,
                                        'tp1', s.entry_price - s.tp1)
                leg1_open = False
                leg2_sl = s.sl_after_tp1  # trail stop on leg 2

            # TP2 (leg 2 target)
            if leg2_open and l <= s.tp2:
                result.leg2 = LegResult(s.direction, s.entry_price, s.tp2,
                                        'tp2', s.entry_price - s.tp2)
                leg2_open = False

        else:  # long
            if leg1_open and l <= s.sl_initial:
                result.leg1 = LegResult(s.direction, s.entry_price, s.sl_initial,
                                        'sl', s.sl_initial - s.entry_price)
                leg1_open = False
            if leg2_open and l <= leg2_sl:
                result.leg2 = LegResult(s.direction, s.entry_price, leg2_sl,
                                        'sl', leg2_sl - s.entry_price)
                leg2_open = False

            if leg1_open and h >= s.tp1:
                result.leg1 = LegResult(s.direction, s.entry_price, s.tp1,
                                        'tp1', s.tp1 - s.entry_price)
                leg1_open = False
                leg2_sl = s.sl_after_tp1

            if leg2_open and h >= s.tp2:
                result.leg2 = LegResult(s.direction, s.entry_price, s.tp2,
                                        'tp2', s.tp2 - s.entry_price)
                leg2_open = False

        if not leg1_open and not leg2_open:
            break

        # Time-stop: mark any still-open legs to market at this bar's close.
        if max_hold_bars is not None and bars_held >= max_hold_bars:
            close = bar['close']
            mtm = (s.entry_price - close) if is_short else (close - s.entry_price)
            if leg1_open:
                result.leg1 = LegResult(s.direction, s.entry_price, close,
                                        'time_stop', mtm)
                leg1_open = False
            if leg2_open:
                result.leg2 = LegResult(s.direction, s.entry_price, close,
                                        'time_stop', mtm)
                leg2_open = False
            break

    return result
