"""
Weekend-risk variant of trade_simulator. Motivated by live Trade 5 (USD/JPY):
a Friday entry held across the weekend, Monday gap ran it to the stop.

The FX series has no weekend bars, so the weekend shows up as a large time gap
between consecutive M15 bars (Fri ~21:00 UTC -> Sun ~21:00 UTC, ~48h). We detect
that gap and, depending on mode, act on any still-open legs:

  - 'baseline'     : do nothing (hold through) — control. Still TAGS the trade as
                     weekend_held so we can split baseline P&L by that flag.
  - 'flat'         : close all open legs at the last pre-weekend bar's close
                     (eliminates weekend gap risk entirely).
  - 'be'           : move stops to breakeven (entry) for the weekend, then keep
                     trading. Caps intended risk but a gap can still jump through it.

Every result carries `.weekend_held` (bool). Point accounting matches
trade_simulator exactly, so figures are comparable to baseline.
"""

import pandas as pd
from trade_simulator import LegResult, TradeResult
from signal_detector import Signal

_GAP = pd.Timedelta(hours=12)   # > any weekday session gap, < the ~48h weekend gap


def simulate(signal: Signal, df: pd.DataFrame, mode: str = 'baseline') -> TradeResult:
    future = df[df.index >= signal.timestamp]
    result = TradeResult(signal=signal)
    result.weekend_held = False
    if future.empty:
        return result

    s = signal
    is_short = s.direction == 'short'
    result.entry_range = s.r4 - s.p if is_short else s.p - s.s4

    leg1_open = True
    leg2_open = True
    leg2_sl   = s.sl_initial
    leg1_sl   = s.sl_initial
    filled    = False
    prev_time = None
    prev_close = None

    def close_leg(which, price, reason):
        nonlocal leg1_open, leg2_open
        pnl = (s.entry_price - price) if is_short else (price - s.entry_price)
        lr = LegResult(s.direction, s.entry_price, price, reason, pnl)
        if which == 1:
            result.leg1 = lr; leg1_open = False
        else:
            result.leg2 = lr; leg2_open = False

    for t, bar in future.iterrows():
        # Weekend boundary = large gap from the previous bar while a leg is open.
        if filled and prev_time is not None and (t - prev_time) > _GAP:
            result.weekend_held = True
            if mode == 'flat':
                if leg1_open: close_leg(1, prev_close, 'weekend_flat')
                if leg2_open: close_leg(2, prev_close, 'weekend_flat')
                break
            elif mode == 'be':
                if is_short:
                    leg1_sl = min(leg1_sl, s.entry_price)
                    leg2_sl = min(leg2_sl, s.entry_price)
                else:
                    leg1_sl = max(leg1_sl, s.entry_price)
                    leg2_sl = max(leg2_sl, s.entry_price)

        if not filled:
            if is_short and bar['high'] >= s.entry_price:
                filled = True
            elif not is_short and bar['low'] <= s.entry_price:
                filled = True
            else:
                prev_time, prev_close = t, bar['close']
                continue

        h, l = bar['high'], bar['low']

        if is_short:
            if leg1_open and h >= leg1_sl:
                close_leg(1, leg1_sl, 'sl' if leg1_sl == s.sl_initial else 'be')
            if leg2_open and h >= leg2_sl:
                close_leg(2, leg2_sl, 'sl' if leg2_sl in (s.sl_initial,) else
                          ('sl_after_tp1' if leg2_sl == s.sl_after_tp1 else 'be'))
            if leg1_open and l <= s.tp1:
                close_leg(1, s.tp1, 'tp1'); leg2_sl = min(leg2_sl, s.sl_after_tp1)
            if leg2_open and l <= s.tp2:
                close_leg(2, s.tp2, 'tp2')
        else:
            if leg1_open and l <= leg1_sl:
                close_leg(1, leg1_sl, 'sl' if leg1_sl == s.sl_initial else 'be')
            if leg2_open and l <= leg2_sl:
                close_leg(2, leg2_sl, 'sl' if leg2_sl in (s.sl_initial,) else
                          ('sl_after_tp1' if leg2_sl == s.sl_after_tp1 else 'be'))
            if leg1_open and h >= s.tp1:
                close_leg(1, s.tp1, 'tp1'); leg2_sl = max(leg2_sl, s.sl_after_tp1)
            if leg2_open and h >= s.tp2:
                close_leg(2, s.tp2, 'tp2')

        prev_time, prev_close = t, bar['close']
        if not leg1_open and not leg2_open:
            break

    return result
