"""
Live signal scanner — checks a single instrument for an R8/S0 signal
on the most recently closed M15 bar using wick-based detection.

Entry rule:
  Short: M15 candle HIGH >= R8 (R4) AND close back below R8
  Long:  M15 candle LOW  <= S0 (S4) AND close back above S0
"""

import sys, os
import pandas as pd

import oanda_client
import config

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backtester'))
import pivot_calculator
import filters as _filters
from signal_detector import Signal


def latest_signal(instrument_key: str):
    """
    Fetch recent candles for `instrument_key` (e.g. 'GBPUSD'), detect whether
    a wick-based R8/S0 signal fired on the most recently closed M15 bar.
    Returns a Signal object or None.
    """
    instr_cfg   = config.INSTRUMENTS[instrument_key]
    oanda_instr = instr_cfg['oanda']
    filter_cfg  = instr_cfg['filter_cfg']

    m15_df = oanda_client.get_candles(oanda_instr, 'M15', config.M15_LOOKBACK)
    h4_df  = oanda_client.get_candles(oanda_instr, 'H4',  config.H4_LOOKBACK)

    if len(m15_df) < 10 or len(h4_df) < 3:
        return None

    h4_shifted = h4_df.shift(1).dropna()
    enriched   = pivot_calculator.assign_to_m15(m15_df, h4_shifted)

    rows = enriched.reset_index()
    n    = len(rows)
    if n < 2:
        return None

    # Check the most recently CLOSED bar (second to last — last may be incomplete)
    curr = rows.iloc[n - 2]
    nxt  = rows.iloc[n - 1]

    # ── Short: wick to R8, close back below ──────────────────────────────────
    if curr['high'] >= curr['R4'] and curr['close'] < curr['R4']:
        r4  = curr['R4']
        r3  = curr['R3']
        r2  = curr['R2']
        p   = curr['P']
        entry_range = r4 - p
        sl          = r4 + (r4 - r3)
        sl_after    = r2 + (r2 - curr['R1'])

        passed, _ = _filters.apply_all(
            enriched, n - 2, 'short', r4, entry_range,
            curr['timestamp'], filter_cfg,
        )
        if passed:
            return Signal(
                timestamp=curr['timestamp'], direction='short',
                entry_price=r4, r4=r4, r2=r2, p=p,
                s2=curr['S2'], s4=curr['S4'],
                sl_initial=sl, sl_after_tp1=sl_after,
            )

    # ── Long: wick to S0, close back above ───────────────────────────────────
    elif curr['low'] <= curr['S4'] and curr['close'] > curr['S4']:
        s4  = curr['S4']
        s3  = curr['S3']
        s2  = curr['S2']
        p   = curr['P']
        entry_range = p - s4
        sl          = s4 - (s3 - s4)
        sl_after    = s2 - (curr['S1'] - s2)

        passed, _ = _filters.apply_all(
            enriched, n - 2, 'long', s4, entry_range,
            curr['timestamp'], filter_cfg,
        )
        if passed:
            return Signal(
                timestamp=curr['timestamp'], direction='long',
                entry_price=s4, r4=curr['R4'], r2=curr['R2'], p=p,
                s2=s2, s4=s4,
                sl_initial=sl, sl_after_tp1=sl_after,
            )

    return None


def pips(price_delta: float, instrument_key: str) -> float:
    pip_size = config.INSTRUMENTS[instrument_key]['pip_size']
    return round(abs(price_delta) / pip_size, 1)
