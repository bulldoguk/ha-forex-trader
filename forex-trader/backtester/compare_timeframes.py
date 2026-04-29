#!/usr/bin/env python3
"""
M1 vs M15 signal timeframe comparison.
Uses the same 4H pivot grid and filters — only the entry detection
timeframe changes. Runs both and prints a side-by-side report.

Usage:
  python3 compare_timeframes.py              # 90 days, GBPUSD
  python3 compare_timeframes.py --days=180
  python3 compare_timeframes.py EURUSD
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

INSTRUMENT = next((a.upper() for a in sys.argv[1:]
                   if not a.startswith('--')), 'GBPUSD')
DAYS = next((int(a.split('=')[1]) for a in sys.argv[1:]
             if a.startswith('--days=')), 90)

# Filter configs scaled per timeframe
# M15: 1 bar = 15 min  →  channel_lookback=60 covers ~15 hours
# M1:  1 bar = 1 min   →  need 900 bars to cover same ~15 hours
M15_FILTERS = dict(FILTER_CFG)   # existing config

M1_FILTERS = {
    **FILTER_CFG,
    'channel_lookback': 900,    # 900 M1 bars ≈ 15 hours (same as 60 M15)
    'fib_lookback':     1800,   # 1800 M1 bars ≈ 30 hours (same as 120 M15)
}


def run_tf(instrument_key: str, granularity: str,
           filter_cfg: dict, h4_df: pd.DataFrame, days: int):
    """Fetch candles at `granularity`, assign 4H pivots, detect signals."""
    oanda_instr = oanda_fetcher.OANDA_INSTRUMENTS[instrument_key]

    print(f"  Fetching {granularity} candles...", end=' ', flush=True)
    raw = oanda_fetcher._fetch_candles(oanda_instr, granularity, days)
    df  = oanda_fetcher._to_dataframe(raw)
    print(f"{len(df)} candles")

    enriched = pivot_calculator.assign_to_m15(df, h4_df)

    # detect_all returns (filtered, all)
    filtered, all_sigs = signal_detector.detect_all(enriched)
    # Override: use our per-TF filter config
    filtered = signal_detector.detect(enriched, filter_cfg=filter_cfg)

    results_f   = [trade_simulator.simulate(s, enriched) for s in filtered]
    results_all = [trade_simulator.simulate(s, enriched) for s in all_sigs]

    df_f   = reporter.summarise(results_f,   instrument_key)
    df_all = reporter.summarise(results_all, instrument_key)

    return df_f, df_all, len(all_sigs), len(filtered)


def print_comparison(label: str, df_f: pd.DataFrame, df_all: pd.DataFrame,
                     raw_n: int, filt_n: int):
    closed_f   = df_f[df_f['outcome']   != 'incomplete'] if not df_f.empty else pd.DataFrame()
    closed_all = df_all[df_all['outcome'] != 'incomplete'] if not df_all.empty else pd.DataFrame()

    def stats(df):
        if df.empty:
            return '—', '—', '—', '—'
        wr  = f"{(df['pnl_points'] > 0).mean()*100:.0f}%"
        exp = f"{df['pnl_points'].mean():+.5f}"
        aw  = f"{df[df['pnl_points']>0]['pnl_points'].mean():+.5f}" if (df['pnl_points']>0).any() else '—'
        al  = f"{df[df['pnl_points']<=0]['pnl_points'].mean():+.5f}" if (df['pnl_points']<=0).any() else '—'
        return wr, exp, aw, al

    wrf, expf, awf, alf       = stats(closed_f)
    wr_all, exp_all, aw_all, al_all = stats(closed_all)

    print(f"\n  {'─'*52}")
    print(f"  {label}")
    print(f"  {'─'*52}")
    print(f"  {'':28} {'Filtered':>10}  {'Unfiltered':>10}")
    print(f"  {'Raw signals':28} {raw_n:>10}  {raw_n:>10}")
    print(f"  {'Signals after filters':28} {filt_n:>10}  {'(all)':>10}")
    print(f"  {'Filled trades':28} {len(closed_f):>10}  {len(closed_all):>10}")
    print(f"  {'Win rate':28} {wrf:>10}  {wr_all:>10}")
    print(f"  {'Expectancy (pts/trade)':28} {expf:>10}  {exp_all:>10}")
    print(f"  {'Avg win':28} {awf:>10}  {aw_all:>10}")
    print(f"  {'Avg loss':28} {alf:>10}  {al_all:>10}")

    if not closed_f.empty:
        print(f"\n  Range buckets (filtered):")
        for lbl, grp in reporter._range_buckets(closed_f):
            wr = (grp['pnl_points'] > 0).mean() * 100 if not grp.empty else float('nan')
            print(f"    {lbl:<24} n={len(grp):>3}  win={wr:.0f}%  "
                  f"avg={grp['pnl_points'].mean():+.5f}" if not grp.empty else f"    {lbl:<24} n=0")


def main():
    print(f"\nTimeframe comparison: {INSTRUMENT}  |  {DAYS} days")
    print(f"{'='*55}")

    # Fetch H4 once — shared by both timeframes
    oanda_instr = oanda_fetcher.OANDA_INSTRUMENTS[INSTRUMENT]
    print(f"  Fetching H4 pivots...", end=' ', flush=True)
    raw_h4 = oanda_fetcher._fetch_candles(oanda_instr, 'H4', DAYS)
    h4_df  = oanda_fetcher._to_dataframe(raw_h4, shift=True)
    print(f"{len(h4_df)} candles")

    # M15
    print(f"\n  Running M15...")
    df_f15, df_all15, raw15, filt15 = run_tf(INSTRUMENT, 'M15', M15_FILTERS, h4_df, DAYS)
    print_comparison('M15 (current)', df_f15, df_all15, raw15, filt15)

    # M1
    print(f"\n  Running M1 (this may take a moment — more candles to fetch)...")
    df_f1, df_all1, raw1, filt1 = run_tf(INSTRUMENT, 'M1', M1_FILTERS, h4_df, DAYS)
    print_comparison('M1 (proposed)', df_f1, df_all1, raw1, filt1)

    # Summary
    print(f"\n{'='*55}")
    print(f"  SUMMARY — {INSTRUMENT}  {DAYS}d")
    print(f"{'='*55}")
    print(f"  {'':28} {'M15':>10}  {'M1':>10}")

    def fmt(df):
        c = df[df['outcome'] != 'incomplete'] if not df.empty and 'outcome' in df.columns else pd.DataFrame()
        n  = f"{len(c):>10}"
        wr = f"{(c['pnl_points']>0).mean()*100:.0f}%":>10 if not c.empty else '—'
        ex = f"{c['pnl_points'].mean():+.5f}" if not c.empty else '—'
        return f"{len(c):>10}", f"{wr:>10}", f"{ex:>10}"

    n15, wr15, ex15 = fmt(df_f15)
    n1,  wr1,  ex1  = fmt(df_f1)
    print(f"  {'Filled trades (filtered)':28} {n15}  {n1}")
    print(f"  {'Win rate':28} {wr15}  {wr1}")
    print(f"  {'Expectancy':28} {ex15}  {ex1}")
    print()


if __name__ == '__main__':
    main()
