#!/usr/bin/env python3
"""
Weekend-risk study. Two questions:
  1. DIAGNOSTIC: in the baseline model, are weekend-held trades actually worse
     than trades that close before the weekend?
  2. FIX: does flattening (or moving to breakeven) before the weekend improve
     overall expectancy / drawdown?

Usage:
  python weekend_study.py                 # six live pairs, 365d
  python weekend_study.py --days=730
  python weekend_study.py GBPUSD USDJPY
"""

import sys
import pandas as pd

import oanda_fetcher
import pivot_calculator
import signal_detector
import weekend_simulator as wsim
from config import FILTER_CFG_OVERRIDES

LIVE_PAIRS = ['GBPUSD', 'EURUSD', 'GBPJPY', 'USDJPY', 'EURJPY', 'USDCAD']
_PIVOT_TF_OVERRIDES = {'USDJPY': 'daily'}
MODES = ['baseline', 'flat', 'be']


def _stats(pnls):
    if not pnls:
        return None
    s = pd.Series(pnls)
    cum = s.cumsum()
    return dict(n=len(s), win=(s > 0).mean()*100, exp=s.mean(),
                total=s.sum(), dd=(cum - cum.cummax()).min())


def _prep(name, days):
    pivot_tf = _PIVOT_TF_OVERRIDES.get(name, '4h')
    m15, pivot_df = oanda_fetcher.fetch(name, days=days, pivot_tf=pivot_tf)
    enriched = pivot_calculator.assign_to_m15(m15, pivot_df, pivot_tf=pivot_tf)
    cfg = FILTER_CFG_OVERRIDES.get(name)
    filtered = signal_detector.detect(enriched, filter_cfg=cfg) if cfg is not None \
        else signal_detector.detect(enriched)
    allsigs = signal_detector.detect(enriched, filter_cfg={})
    return enriched, filtered, allsigs


def main():
    args = [a.upper() for a in sys.argv[1:] if not a.startswith('--')]
    days = 365
    for a in sys.argv[1:]:
        if a.startswith('--days='):
            days = int(a.split('=')[1])
    targets = [a for a in args if a in LIVE_PAIRS] or LIVE_PAIRS

    # Aggregators
    split = {'wknd': [], 'intraday': []}         # baseline, filtered set
    overall = {m: [] for m in MODES}             # filtered set
    overall_all = {m: [] for m in MODES}         # unfiltered set
    n_wknd_total = n_total = 0

    for name in targets:
        try:
            enriched, filtered, allsigs = _prep(name, days)
        except Exception as e:
            print(f"  Skipping {name}: {e}")
            continue

        # Diagnostic split on the filtered (live-strategy) set, baseline mode
        base = [wsim.simulate(s, enriched, 'baseline') for s in filtered]
        base = [r for r in base if r.leg1 and r.leg2]
        wknd = [r.total_pnl for r in base if r.weekend_held]
        intr = [r.total_pnl for r in base if not r.weekend_held]
        split['wknd'] += wknd
        split['intraday'] += intr
        n_wknd_total += len(wknd); n_total += len(base)
        print(f"\n  {name}: {len(base)} filtered trades, "
              f"{len(wknd)} weekend-held ({len(wknd)/max(len(base),1)*100:.0f}%)")

        for m in MODES:
            rf = [wsim.simulate(s, enriched, m) for s in filtered]
            overall[m] += [r.total_pnl for r in rf if r.leg1 and r.leg2]
            ra = [wsim.simulate(s, enriched, m) for s in allsigs]
            overall_all[m] += [r.total_pnl for r in ra if r.leg1 and r.leg2]

    print(f"\n{'#'*72}\n  DIAGNOSTIC — baseline P&L split by weekend exposure (filtered, all pairs)\n{'#'*72}")
    print(f"  Weekend-held trades: {n_wknd_total} of {n_total} "
          f"({n_wknd_total/max(n_total,1)*100:.0f}%)")
    for label in ('intraday', 'wknd'):
        st = _stats(split[label])
        if st:
            tag = 'closed before weekend' if label == 'intraday' else 'HELD over weekend'
            print(f"    {tag:<24} n={st['n']:>4}  win={st['win']:>5.1f}%  "
                  f"exp={st['exp']:>+10.5f}  total={st['total']:>+10.4f}")

    for slabel, store in [('FILTERED — live strategy', overall),
                          ('UNFILTERED — large sample', overall_all)]:
        print(f"\n{'#'*72}\n  FIX COMPARISON — {slabel} (all pairs)\n{'#'*72}")
        print(f"    {'mode':<12}{'n':>5}{'win%':>7}{'exp(pts)':>11}{'total':>11}{'maxDD':>11}")
        for m in MODES:
            st = _stats(store[m])
            if st:
                print(f"    {m:<12}{st['n']:>5}{st['win']:>6.1f}%{st['exp']:>11.5f}"
                      f"{st['total']:>11.4f}{st['dd']:>11.5f}")


if __name__ == '__main__':
    main()
