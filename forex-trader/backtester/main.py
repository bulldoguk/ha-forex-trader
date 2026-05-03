#!/usr/bin/env python3
"""
Pivot mean-reversion backtester.

Usage:
  python main.py                         # run all instruments
  python main.py GBPUSD GOLD             # run specific instruments
  python main.py --plot GBPUSD           # run + save equity chart
  python main.py --days 365 GBPUSD       # override history window
  python main.py --yf GBPUSD             # use yfinance instead of OANDA
"""

import sys
import pandas as pd
import pivot_calculator
import signal_detector
import trade_simulator
import reporter
from config import INSTRUMENTS, FILTER_CFG_OVERRIDES
from oanda_fetcher import OANDA_INSTRUMENTS

# Instruments that use a non-default pivot timeframe
_PIVOT_TF_OVERRIDES = {
    'USDJPY': 'daily',
    'GOLD':   'daily',
}


def run(name: str, days: int = 365, plot: bool = False,
        use_yf: bool = False, pivot_tf: str = None,
        trend_filter: bool = False) -> pd.DataFrame:
    pivot_tf = pivot_tf or _PIVOT_TF_OVERRIDES.get(name, '4h')
    filter_cfg = FILTER_CFG_OVERRIDES.get(name)   # None → use module default

    print(f"\nFetching {name} ({days}d history, pivot={pivot_tf})...")
    try:
        if use_yf:
            import data_fetcher
            ticker = INSTRUMENTS.get(name)
            if not ticker:
                print(f"  Skipping {name}: not in yfinance instrument list")
                return pd.DataFrame()
            m15, pivot_df = data_fetcher.fetch(ticker)
        else:
            import oanda_fetcher
            m15, pivot_df = oanda_fetcher.fetch(name, days=days, pivot_tf=pivot_tf)
    except Exception as e:
        print(f"  Skipping {name}: {e}")
        return pd.DataFrame()

    print(f"  M15 bars: {len(m15)}  |  {pivot_tf.upper()} bars: {len(pivot_df)}")

    enriched = pivot_calculator.assign_to_m15(m15, pivot_df, pivot_tf=pivot_tf)

    if filter_cfg is not None:
        raw_cfg  = {k: v for k, v in filter_cfg.items() if k == 'entry_level'}
        all_sigs = signal_detector.detect(enriched, filter_cfg=raw_cfg)
        filtered = signal_detector.detect(enriched, filter_cfg=filter_cfg)
        trend_cfg = {**filter_cfg, 'use_donchian_trend': True}
    else:
        filtered, all_sigs = signal_detector.detect_all(enriched)
        from config import FILTER_CFG
        trend_cfg = {**FILTER_CFG, 'use_donchian_trend': True}

    print(f"  Raw signals: {len(all_sigs)}  |  After filters: {len(filtered)}")

    results_filtered = [trade_simulator.simulate(s, enriched) for s in filtered]
    df_filtered = reporter.summarise(results_filtered, name)
    print("\n  [Filtered — existing]")
    reporter.print_report(df_filtered, name)

    if trend_filter:
        trend_sigs = signal_detector.detect(enriched, filter_cfg=trend_cfg)
        print(f"  After Donchian trend filter: {len(trend_sigs)} signals "
              f"({len(filtered) - len(trend_sigs)} blocked by trend direction)")
        results_trend = [trade_simulator.simulate(s, enriched) for s in trend_sigs]
        df_trend = reporter.summarise(results_trend, name)
        print("\n  [Filtered + Donchian trend alignment]")
        reporter.print_report(df_trend, name)

    results_all = [trade_simulator.simulate(s, enriched) for s in all_sigs]
    df_all = reporter.summarise(results_all, name)
    print("\n  [Unfiltered — baseline]")
    reporter.print_report(df_all, name)

    if plot:
        reporter.plot_equity(df_filtered, f"{name}_filtered")
        if trend_filter:
            reporter.plot_equity(df_trend, f"{name}_trend_filtered")

    return df_trend if trend_filter else df_filtered


def main():
    args         = [a for a in sys.argv[1:] if not a.startswith('--')]
    plot         = '--plot'          in sys.argv
    use_yf       = '--yf'            in sys.argv
    trend_filter = '--trend-filter'  in sys.argv

    days = 365
    pivot_tf_override = None
    for arg in sys.argv[1:]:
        if arg.startswith('--days='):
            days = int(arg.split('=')[1])
        elif arg.startswith('--pivot-tf='):
            pivot_tf_override = arg.split('=')[1]

    available = list(OANDA_INSTRUMENTS.keys())
    targets   = [a.upper() for a in args if a.upper() in available] or available

    if not targets:
        print(f"Unknown instrument(s). Available: {available}")
        sys.exit(1)

    all_results = []
    for name in targets:
        df = run(name, days=days, plot=plot, use_yf=use_yf,
                 pivot_tf=pivot_tf_override, trend_filter=trend_filter)
        if not df.empty:
            all_results.append(df)

    if len(all_results) > 1:
        combined = pd.concat(all_results)
        print(f"\n{'='*50}")
        print(f"  COMBINED  —  {len(combined)} trades across {len(all_results)} instruments")
        print(f"{'='*50}")
        closed = combined[combined['outcome'] != 'incomplete']
        if not closed.empty:
            print(f"  Overall win rate: {(closed['pnl_points'] > 0).mean()*100:.1f}%")
            print(f"  Overall expectancy: {closed['pnl_points'].mean():+.5f} pts/trade")

        combined.to_csv('backtest_results.csv', index=False)
        print(f"\n  Full results saved: backtest_results.csv")


if __name__ == '__main__':
    main()
