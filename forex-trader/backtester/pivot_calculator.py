"""
Standard extended floor pivot calculator.

Level mapping (strategy label → standard MT label):
  R8 = R4,  R6 = R3,  R5 = R2,  P4 = P,  S3 = S2,  S2 = S1,  S0 = S4

Spacing: R1/S1 are asymmetric. From R2/S2 outward each level is exactly
one (H-L) interval apart.
"""

from dataclasses import dataclass
import pandas as pd


@dataclass
class PivotLevels:
    P:  float   # P4  — central pivot
    R1: float   # R5
    R2: float   # R6  (TP1 for shorts)
    R3: float   # R7
    R4: float   # R8  (entry for shorts)
    S1: float   # S3
    S2: float   # S2  (TP1 for longs)
    S3: float   # S1
    S4: float   # S0  (entry for longs)

    @property
    def r8(self) -> float: return self.R4
    @property
    def r6(self) -> float: return self.R2  # TP1 short → P4
    @property
    def p4(self) -> float: return self.P   # TP2 both directions
    @property
    def s2(self) -> float: return self.S2  # TP1 long → P4
    @property
    def s0(self) -> float: return self.S4

    def sl_above_r8(self) -> float:
        """SL for short: one full level above R8."""
        return self.R4 + (self.R4 - self.R3)

    def sl_below_s0(self) -> float:
        """SL for long: one full level below S0."""
        return self.S4 - (self.S3 - self.S4)

    def sl_above_r6(self) -> float:
        """Trailing SL after TP1 (short): one level above R6."""
        return self.R2 + (self.R2 - self.R1)

    def sl_below_s2(self) -> float:
        """Trailing SL after TP1 (long): one level below S2."""
        return self.S2 - (self.S1 - self.S2)

    def range_r8_to_p4(self) -> float:
        return abs(self.R4 - self.P)

    def range_s0_to_p4(self) -> float:
        return abs(self.S4 - self.P)


def calculate(h: float, l: float, c: float) -> PivotLevels:
    P  = (h + l + c) / 3
    rng = h - l

    R1 = 2 * P - l
    R2 = P + rng
    R3 = h + 2 * (P - l)
    R4 = R3 + rng

    S1 = 2 * P - h
    S2 = P - rng
    S3 = l - 2 * (h - P)
    S4 = S3 - rng

    return PivotLevels(P=P, R1=R1, R2=R2, R3=R3, R4=R4,
                       S1=S1, S2=S2, S3=S3, S4=S4)


def assign_to_m15(m15: pd.DataFrame, pivot_src: pd.DataFrame,
                  pivot_tf: str = '4h') -> pd.DataFrame:
    """
    For each M15 bar, look up the most recently completed pivot-source candle
    and attach its pivot levels as columns.
    pivot_tf is used only to name the source timestamp column (e.g. 'pivot_4h_ts').
    """
    records = []
    src_times = pivot_src.index.sort_values()

    for ts, row in m15.iterrows():
        past = src_times[src_times <= ts]
        if past.empty:
            continue
        src_row = pivot_src.loc[past[-1]]
        pivots = calculate(src_row['high'], src_row['low'], src_row['close'])
        records.append({
            'timestamp': ts,
            'open':  row['open'],
            'high':  row['high'],
            'low':   row['low'],
            'close': row['close'],
            'P':  pivots.P,
            'R1': pivots.R1, 'R2': pivots.R2,
            'R3': pivots.R3, 'R4': pivots.R4,
            'S1': pivots.S1, 'S2': pivots.S2,
            'S3': pivots.S3, 'S4': pivots.S4,
            f'pivot_{pivot_tf}_ts': past[-1],
        })

    out = pd.DataFrame(records).set_index('timestamp')
    return out
