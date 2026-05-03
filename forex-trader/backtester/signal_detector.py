"""
Detects entry signals at R8 (short) and S0 (long).

Entry rule (wick-based — single candle):
  - Short: M15 candle HIGH >= R8 (R4) AND candle CLOSES back below R8
  - Long:  M15 candle LOW  <= S0 (S4) AND candle CLOSES back above S0

This captures price touching R8/S0 with a rejection close in the same candle,
which is how limit orders at the level are filled in practice. A previous
close-based approach (close above then close below) introduced a pivot-shift
bug at 4H candle boundaries and missed many valid wick touches.

Optional filters (configured via config.FILTER_CFG):
  - Minimum range (R8/S0 → P4 distance) — recalibrated to 0.0041 (41 pips)
  - Maximum range (for Gold — inverted pattern)
  - Session (London / New York)
  - Trend channel (linear regression)
  - Fibonacci confluence
"""

import pandas as pd
from dataclasses import dataclass, field
import filters


@dataclass
class Signal:
    timestamp:    object   # entry candle timestamp
    direction:    str      # 'short' or 'long'
    entry_price:  float
    r4:  float             # R8 level at entry
    r2:  float             # R6 — TP1 for short
    p:   float             # P4 — TP2 for both
    s2:  float             # S2 — TP1 for long
    s4:  float             # S0 level at entry
    sl_initial:   float
    sl_after_tp1: float
    filters_passed: list = field(default_factory=list)
    filters_failed: list = field(default_factory=list)

    @property
    def tp1(self) -> float:
        return self.r2 if self.direction == 'short' else self.s2

    @property
    def tp2(self) -> float:
        return self.p


def detect(df: pd.DataFrame, filter_cfg: dict = None) -> list[Signal]:
    """
    df must have columns: open, high, low, close, R1-R4, S1-S4, P
    (output of pivot_calculator.assign_to_m15)

    Returns signals that pass the active filters.
    Pass filter_cfg={} to disable all filters (raw signal scan).
    """
    if filter_cfg is None:
        from config import FILTER_CFG
        filter_cfg = FILTER_CFG

    signals = []
    rows    = df.reset_index()
    use_r2  = filter_cfg.get('entry_level') == 'R2'

    for i in range(1, len(rows) - 1):
        curr = rows.iloc[i]
        nxt  = rows.iloc[i + 1]

        if use_r2:
            # --- Short: wick to R2 (R6 in strategy naming), close back below ---
            if curr['high'] >= curr['R2'] and curr['close'] < curr['R2']:
                entry = curr['R2']
                tp1   = curr['R1']
                p     = curr['P']
                entry_range = entry - p
                sl          = entry + (entry - tp1)
                sl_after    = tp1   + (tp1  - p)

                passed, failed = filters.apply_all(
                    df, i, 'short', entry, entry_range, curr['timestamp'], filter_cfg,
                )
                signals.append(Signal(
                    timestamp=nxt['timestamp'], direction='short',
                    entry_price=entry, r4=entry, r2=tp1, p=p,
                    s2=curr['S1'], s4=curr['S2'],
                    sl_initial=sl, sl_after_tp1=sl_after,
                    filters_passed=[] if failed else list(filter_cfg.keys()),
                    filters_failed=failed,
                ))

            # --- Long: wick to S2, close back above ---
            elif curr['low'] <= curr['S2'] and curr['close'] > curr['S2']:
                entry = curr['S2']
                tp1   = curr['S1']
                p     = curr['P']
                entry_range = p - entry
                sl          = entry - (tp1 - entry)
                sl_after    = tp1   - (p   - tp1)

                passed, failed = filters.apply_all(
                    df, i, 'long', entry, entry_range, curr['timestamp'], filter_cfg,
                )
                signals.append(Signal(
                    timestamp=nxt['timestamp'], direction='long',
                    entry_price=entry, r4=curr['R2'], r2=curr['R1'], p=p,
                    s2=tp1, s4=entry,
                    sl_initial=sl, sl_after_tp1=sl_after,
                    filters_passed=[] if failed else list(filter_cfg.keys()),
                    filters_failed=failed,
                ))

        else:
            # --- Short: wick to R8 (R4), close back below ---
            if curr['high'] >= curr['R4'] and curr['close'] < curr['R4']:
                r4  = curr['R4']
                r3  = curr['R3']
                r2  = curr['R2']
                p   = curr['P']
                entry_range = r4 - p
                sl          = r4 + (r4 - r3)
                sl_after    = r2 + (r2 - curr['R1'])

                passed, failed = filters.apply_all(
                    df, i, 'short', r4, entry_range, curr['timestamp'], filter_cfg,
                )
                signals.append(Signal(
                    timestamp=nxt['timestamp'], direction='short',
                    entry_price=r4, r4=r4, r2=r2, p=p,
                    s2=curr['S2'], s4=curr['S4'],
                    sl_initial=sl, sl_after_tp1=sl_after,
                    filters_passed=[] if failed else list(filter_cfg.keys()),
                    filters_failed=failed,
                ))

            # --- Long: wick to S0 (S4), close back above ---
            elif curr['low'] <= curr['S4'] and curr['close'] > curr['S4']:
                s4  = curr['S4']
                s3  = curr['S3']
                s2  = curr['S2']
                p   = curr['P']
                entry_range = p - s4
                sl          = s4 - (s3 - s4)
                sl_after    = s2 - (curr['S1'] - s2)

                passed, failed = filters.apply_all(
                    df, i, 'long', s4, entry_range, curr['timestamp'], filter_cfg,
                )
                signals.append(Signal(
                    timestamp=nxt['timestamp'], direction='long',
                    entry_price=s4, r4=curr['R4'], r2=curr['R2'], p=p,
                    s2=s2, s4=s4,
                    sl_initial=sl, sl_after_tp1=sl_after,
                    filters_passed=[] if failed else list(filter_cfg.keys()),
                    filters_failed=failed,
                ))

    # Show filter rejection breakdown
    if filter_cfg and signals:
        from collections import Counter
        all_failed = [f for s in signals for f in s.filters_failed]
        if all_failed:
            counts = Counter(all_failed)
            print(f"  Filter rejections: " +
                  ", ".join(f"{k}={v}" for k, v in counts.items()) +
                  f" (of {len(signals)} raw signals)")

    return [s for s in signals if not s.filters_failed]


def detect_all(df: pd.DataFrame) -> tuple[list[Signal], list[Signal]]:
    """Returns (filtered_signals, all_signals) for comparison reporting."""
    all_sigs      = detect(df, filter_cfg={})
    filtered_sigs = detect(df)
    return filtered_sigs, all_sigs
