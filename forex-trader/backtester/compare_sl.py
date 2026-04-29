#!/usr/bin/env python3
"""
Compare pivot SL vs tight (candle-structure) SL.

Pivot SL  : one full pivot level beyond R8/S0 (~50-80 pips)
Tight SL  : high/low of the M15 return candle + pip buffer (~10-30 pips)

Both use identical entry prices and TP levels — only the initial SL changes.
sl_after_tp1 uses the same "one level beyond TP1" trailing logic in both cases.

Usage:
  python3 compare_sl.py                  # 365d GBPUSD
  python3 compare_sl.py --days=180 EURUSD
  python3 compare_sl.py --buffer=3       # 3-pip buffer instead of 5
"""

import sys, warnings
warnings.filterwarnings('ignore')

import pandas as pd
import oanda_fetcher
import pivot_calculator
import signal_detector
import trade_simulator
import reporter
from config import FILTER_CFG
from signal_detector import Signal
import filters as _filters

INSTRUMENT  = next((a.upper() for a in sys.argv[1:] if not a.startswith('--')), 'GBPUSD')
DAYS        = next((int(a.split('=')[1]) for a in sys.argv[1:] if a.startswith('--days=')), 365)
BUFFER_PIPS = next((int(a.split('=')[1]) for a in sys.argv[1:] if a.startswith('--buffer=')), 5)
PIP         = 0.0001   # GBP/USD, EUR/USD — adjust for other instruments


def detect_with_tight_sl(df: pd.DataFrame, filter_cfg: dict,
                          buffer: float) -> list[Signal]:
    """
    Same signal logic as signal_detector.detect() but SL is set to
    the return candle's high/low + buffer instead of one pivot level.
    """
    signals = []
    rows    = df.reset_index()

    for i in range(1, len(rows) - 1):
        prev = rows.iloc[i - 1]
        curr = rows.iloc[i]
        nxt  = rows.iloc[i + 1]

        # Skip if 4H pivot grid shifted between these candles
        if prev.get('pivot_4h_ts') != curr.get('pivot_4h_ts'):
            continue

        # Short
        if prev['close'] > prev['R4'] and curr['close'] < curr['R4']:
            r4  = curr['R4']
            r2  = curr['R2']
            p   = curr['P']
            entry_range = r4 - p

            passed, _ = _filters.apply_all(
                df, i, 'short', r4, entry_range, curr['timestamp'], filter_cfg
            )
            if not passed:
                continue

            # Tight SL: highest high across violation candle AND return candle + buffer
            # (price could have peaked on either candle during the R8 breach)
            violation_high = max(prev['high'], curr['high'])
            sl       = violation_high + buffer
            sl_after = r2 + (r2 - curr['R1'])

            signals.append(Signal(
                timestamp=nxt['timestamp'], direction='short',
                entry_price=r4, r4=r4, r2=r2, p=p,
                s2=curr['S2'], s4=curr['S4'],
                sl_initial=sl, sl_after_tp1=sl_after,
            ))

        # Long
        elif prev['close'] < prev['S4'] and curr['close'] > curr['S4']:
            s4  = curr['S4']
            s2  = curr['S2']
            p   = curr['P']
            entry_range = p - s4

            passed, _ = _filters.apply_all(
                df, i, 'long', s4, entry_range, curr['timestamp'], filter_cfg
            )
            if not passed:
                continue

            # Tight SL: lowest low across violation candle AND return candle - buffer
            violation_low = min(prev['low'], curr['low'])
            sl       = violation_low - buffer
            sl_after = s2 - (curr['S1'] - s2)

            signals.append(Signal(
                timestamp=nxt['timestamp'], direction='long',
                entry_price=s4, r4=curr['R4'], r2=curr['R2'], p=p,
                s2=s2, s4=s4,
                sl_initial=sl, sl_after_tp1=sl_after,
            ))

    return signals


def stats(df: pd.DataFrame) -> dict:
    if df.empty or 'outcome' not in df.columns:
        return {}
    c = df[df['outcome'] != 'incomplete']
    if c.empty:
        return {}
    wins   = c[c['pnl_points'] > 0]
    losses = c[c['pnl_points'] <= 0]
    return {
        'trades':      len(c),
        'win_rate':    (c['pnl_points'] > 0).mean() * 100,
        'expectancy':  c['pnl_points'].mean(),
        'avg_win':     wins['pnl_points'].mean()   if not wins.empty   else 0,
        'avg_loss':    losses['pnl_points'].mean() if not losses.empty else 0,
        'max_dd':      c['pnl_points'].cumsum().sub(c['pnl_points'].cumsum().cummax()).min(),
        'outcomes':    c['outcome'].value_counts().to_dict(),
    }


def print_side_by_side(pivot_st: dict, tight_st: dict, buffer_pips: int):
    def f(d, key, fmt='{:.4f}'):
        v = d.get(key)
        return fmt.format(v) if v is not None else '—'

    print(f"\n  {'Metric':<28} {'Pivot SL':>12}  {'Tight SL (' + str(buffer_pips) + 'p buffer)':>18}")
    print(f"  {'─'*62}")
    print(f"  {'Filled trades':<28} {f(pivot_st,'trades','{:.0f}'):>12}  {f(tight_st,'trades','{:.0f}'):>18}")
    print(f"  {'Win rate':<28} {f(pivot_st,'win_rate','{:.1f}%'):>12}  {f(tight_st,'win_rate','{:.1f}%'):>18}")
    print(f"  {'Expectancy (pts)':<28} {f(pivot_st,'expectancy','{:+.5f}'):>12}  {f(tight_st,'expectancy','{:+.5f}'):>18}")
    print(f"  {'Avg win (pts)':<28} {f(pivot_st,'avg_win','{:+.5f}'):>12}  {f(tight_st,'avg_win','{:+.5f}'):>18}")
    print(f"  {'Avg loss (pts)':<28} {f(pivot_st,'avg_loss','{:+.5f}'):>12}  {f(tight_st,'avg_loss','{:+.5f}'):>18}")
    print(f"  {'Max drawdown (pts)':<28} {f(pivot_st,'max_dd','{:+.5f}'):>12}  {f(tight_st,'max_dd','{:+.5f}'):>18}")

    # Avg win / avg loss ratio
    for label, st in [('Pivot SL', pivot_st), ('Tight SL', tight_st)]:
        aw = st.get('avg_win',  0)
        al = st.get('avg_loss', 0)
        if aw and al and al != 0:
            rr = abs(aw / al)
            print(f"  {label} R:R ratio: {rr:.2f}:1")

    print(f"\n  Outcomes:")
    all_keys = set(pivot_st.get('outcomes', {}).keys()) | set(tight_st.get('outcomes', {}).keys())
    for k in sorted(all_keys):
        pv = pivot_st.get('outcomes', {}).get(k, 0)
        tv = tight_st.get('outcomes', {}).get(k, 0)
        print(f"    {k:<20} {pv:>5} (pivot)   {tv:>5} (tight)")


def main():
    print(f"\nSL Comparison: {INSTRUMENT}  |  {DAYS}d  |  tight buffer = {BUFFER_PIPS} pips")
    print(f"{'='*60}")

    oanda_instr = oanda_fetcher.OANDA_INSTRUMENTS[INSTRUMENT]

    print("Fetching M15 and H4 data...")
    m15_raw = oanda_fetcher._fetch_candles(oanda_instr, 'M15', DAYS)
    h4_raw  = oanda_fetcher._fetch_candles(oanda_instr, 'H4',  DAYS)
    m15_df  = oanda_fetcher._to_dataframe(m15_raw)
    h4_df   = oanda_fetcher._to_dataframe(h4_raw, shift=True)
    print(f"M15: {len(m15_df)} candles  |  H4: {len(h4_df)} candles")

    enriched = pivot_calculator.assign_to_m15(m15_df, h4_df)

    # Pivot SL (current approach)
    pivot_sigs = signal_detector.detect(enriched, filter_cfg=FILTER_CFG)
    pivot_results = [trade_simulator.simulate(s, enriched) for s in pivot_sigs]
    pivot_df      = reporter.summarise(pivot_results, INSTRUMENT)

    # Tight SL
    buffer     = BUFFER_PIPS * PIP
    tight_sigs = detect_with_tight_sl(enriched, FILTER_CFG, buffer)
    tight_results = [trade_simulator.simulate(s, enriched) for s in tight_sigs]
    tight_df      = reporter.summarise(tight_results, INSTRUMENT)

    print(f"\nSignals: pivot={len(pivot_sigs)}  tight={len(tight_sigs)}  "
          f"(same signals, different SL)")

    # SL size analysis
    print(f"\n  Typical SL sizes ({INSTRUMENT}):")
    if pivot_sigs:
        pivot_sl_pips = [(s.sl_initial - s.entry_price) / PIP
                         if s.direction == 'short'
                         else (s.entry_price - s.sl_initial) / PIP
                         for s in pivot_sigs]
        print(f"  Pivot SL:  avg {pd.Series(pivot_sl_pips).mean():.0f} pips  "
              f"(range {min(pivot_sl_pips):.0f}–{max(pivot_sl_pips):.0f})")
    if tight_sigs:
        tight_sl_pips = [(s.sl_initial - s.entry_price) / PIP
                          if s.direction == 'short'
                          else (s.entry_price - s.sl_initial) / PIP
                          for s in tight_sigs]
        print(f"  Tight SL:  avg {pd.Series(tight_sl_pips).mean():.0f} pips  "
              f"(range {min(tight_sl_pips):.0f}–{max(tight_sl_pips):.0f})")

    pivot_st = stats(pivot_df)
    tight_st = stats(tight_df)

    print_side_by_side(pivot_st, tight_st, BUFFER_PIPS)


if __name__ == '__main__':
    main()
