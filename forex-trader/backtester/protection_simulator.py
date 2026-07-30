"""
Variant of trade_simulator that adds an EARLY profit-protection stop, independent
of TP1. Motivated by live Trade 5 (USD/JPY, 2026-06-22): the trade ran ~74% of the
way to TP1 (+$33 unrealized) then reversed to a full stop-out, because the existing
profit-lock (move stop to `sl_after_tp1`) only arms AFTER TP1 is hit.

Three modes:
  - 'baseline'   : identical behaviour to trade_simulator.simulate (control).
  - 'breakeven'  : once max-favourable-excursion (MFE) reaches `be_trigger_frac`
                   of the entry->TP1 distance, move BOTH open legs' stop to
                   entry (optionally locking `be_buffer_frac` of TP1 distance).
  - 'trailing'   : once MFE reaches `trail_activate_frac` of entry->TP1 distance,
                   trail the stop `trail_frac` * (entry->TP1 distance) behind the
                   best price; never loosens.

Conservative design (no look-ahead): the protective stop for bar N is computed
from MFE through bar N-1 only. Within a bar we check the stop (worst case) before
the targets, exactly like the baseline simulator. The protective stop is only ever
taken when it is TIGHTER than the strategy's existing stop, so it can never make a
trade worse than baseline on the stop side — it can only cut a loss earlier (or,
the cost we're measuring, stop out a trade that would later have reached TP1/TP2).

Point accounting matches trade_simulator exactly (sum of the two legs' point moves),
so results are directly comparable to the existing baseline numbers.
"""

import pandas as pd
from typing import Optional
from trade_simulator import LegResult, TradeResult
from signal_detector import Signal


def _protective_stop(mode, is_short, entry, dist1, mfe_ext,
                     be_trigger_frac, be_buffer_frac,
                     trail_activate_frac, trail_frac):
    """
    Return the protective stop PRICE given the favourable extreme seen so far,
    or None if protection is not yet armed. dist1 = |entry - tp1| (>0).
    mfe_ext = best price seen so far (lowest low for short, highest high for long).
    """
    if mode == 'baseline' or dist1 <= 0 or mfe_ext is None:
        return None

    fav = (entry - mfe_ext) if is_short else (mfe_ext - entry)   # favourable distance (>=0)
    if fav <= 0:
        return None

    if mode == 'breakeven':
        if fav >= be_trigger_frac * dist1:
            lock = be_buffer_frac * dist1   # 0 = pure breakeven
            return (entry - lock) if is_short else (entry + lock)
        return None

    if mode == 'trailing':
        if fav >= trail_activate_frac * dist1:
            gap = trail_frac * dist1
            return (mfe_ext + gap) if is_short else (mfe_ext - gap)
        return None

    return None


def simulate(signal: Signal, df: pd.DataFrame, mode: str = 'baseline',
             be_trigger_frac: float = 0.7, be_buffer_frac: float = 0.0,
             trail_activate_frac: float = 0.5, trail_frac: float = 0.5) -> TradeResult:
    future = df[df.index >= signal.timestamp]
    if future.empty:
        return TradeResult(signal=signal)

    s = signal
    is_short = s.direction == 'short'
    result = TradeResult(
        signal=signal,
        entry_range=s.r4 - s.p if is_short else s.p - s.s4,
    )

    dist1 = abs(s.entry_price - s.tp1)

    leg1_open = True
    leg2_open = True
    leg1_sl   = s.sl_initial
    leg2_sl   = s.sl_initial
    filled    = False
    mfe_ext: Optional[float] = None   # best price through PRIOR bars only

    def reason_for(stop_price):
        """Classify which stop level was hit, for reporting."""
        if abs(stop_price - s.sl_initial) < 1e-12:
            return 'sl'
        if abs(stop_price - s.sl_after_tp1) < 1e-12:
            return 'sl_after_tp1'
        return 'be' if mode == 'breakeven' else 'trail'

    for _, bar in future.iterrows():
        if not filled:
            if is_short and bar['high'] >= s.entry_price:
                filled = True
            elif not is_short and bar['low'] <= s.entry_price:
                filled = True
            else:
                continue

        # Apply protection computed from PRIOR-bar MFE (tighten stops only).
        prot = _protective_stop(mode, is_short, s.entry_price, dist1, mfe_ext,
                                be_trigger_frac, be_buffer_frac,
                                trail_activate_frac, trail_frac)
        if prot is not None:
            if is_short:
                if leg1_open:
                    leg1_sl = min(leg1_sl, prot)
                if leg2_open:
                    leg2_sl = min(leg2_sl, prot)
            else:
                if leg1_open:
                    leg1_sl = max(leg1_sl, prot)
                if leg2_open:
                    leg2_sl = max(leg2_sl, prot)

        h, l = bar['high'], bar['low']

        if is_short:
            # Stops first (worst case within bar)
            if leg1_open and h >= leg1_sl:
                result.leg1 = LegResult(s.direction, s.entry_price, leg1_sl,
                                        reason_for(leg1_sl), s.entry_price - leg1_sl)
                leg1_open = False
            if leg2_open and h >= leg2_sl:
                result.leg2 = LegResult(s.direction, s.entry_price, leg2_sl,
                                        reason_for(leg2_sl), s.entry_price - leg2_sl)
                leg2_open = False

            if leg1_open and l <= s.tp1:
                result.leg1 = LegResult(s.direction, s.entry_price, s.tp1,
                                        'tp1', s.entry_price - s.tp1)
                leg1_open = False
                leg2_sl = min(leg2_sl, s.sl_after_tp1)   # existing lock; keep tighter

            if leg2_open and l <= s.tp2:
                result.leg2 = LegResult(s.direction, s.entry_price, s.tp2,
                                        'tp2', s.entry_price - s.tp2)
                leg2_open = False

        else:  # long
            if leg1_open and l <= leg1_sl:
                result.leg1 = LegResult(s.direction, s.entry_price, leg1_sl,
                                        reason_for(leg1_sl), leg1_sl - s.entry_price)
                leg1_open = False
            if leg2_open and l <= leg2_sl:
                result.leg2 = LegResult(s.direction, s.entry_price, leg2_sl,
                                        reason_for(leg2_sl), leg2_sl - s.entry_price)
                leg2_open = False

            if leg1_open and h >= s.tp1:
                result.leg1 = LegResult(s.direction, s.entry_price, s.tp1,
                                        'tp1', s.tp1 - s.entry_price)
                leg1_open = False
                leg2_sl = max(leg2_sl, s.sl_after_tp1)

            if leg2_open and h >= s.tp2:
                result.leg2 = LegResult(s.direction, s.entry_price, s.tp2,
                                        'tp2', s.tp2 - s.entry_price)
                leg2_open = False

        # Update MFE with THIS bar (affects next bar's protection only).
        if is_short:
            mfe_ext = l if mfe_ext is None else min(mfe_ext, l)
        else:
            mfe_ext = h if mfe_ext is None else max(mfe_ext, h)

        if not leg1_open and not leg2_open:
            break

    return result
