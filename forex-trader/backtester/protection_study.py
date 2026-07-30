#!/usr/bin/env python3
"""
Protection study: does an early breakeven / trailing stop improve the EXISTING
pivot mean-reversion strategy?

Compares the baseline two-leg model against breakeven and trailing variants across
the six live instruments, on both the filtered (live-strategy) signal set and the
unfiltered set (larger sample for statistical power).

Usage:
  python protection_study.py                 # all six live pairs, 365d
  python protection_study.py --days=730       # 2 years
  python protection_study.py GBPUSD USDJPY     # subset
"""

import sys
import pandas as pd

import oanda_fetcher
import pivot_calculator
import signal_detector
import protection_simulator as psim
from config import FILTER_CFG_OVERRIDES, FILTER_CFG

LIVE_PAIRS = ['GBPUSD', 'EURUSD', 'GBPJPY', 'USDJPY', 'EURJPY', 'USDCAD']
_PIVOT_TF_OVERRIDES = {'USDJPY': 'daily'}

# Models to compare: (label, kwargs)
MODELS = [
    ('baseline',        dict(mode='baseline')),
    ('BE @50%',         dict(mode='breakeven', be_trigger_frac=0.50)),
    ('BE @70%',         dict(mode='breakeven', be_trigger_frac=0.70)),
    ('BE @70% +10%lock', dict(mode='breakeven', be_trigger_frac=0.70, be_buffer_frac=0.10)),
    ('Trail 50/50',     dict(mode='trailing', trail_activate_frac=0.50, trail_frac=0.50)),
]


def _metrics(results):
    rows = []
    for r in results:
        if not r.leg1 or not r.leg2:
            continue   # incomplete — drop, same as reporter
        rows.append(r.total_pnl)
    if not rows:
        return None
    s = pd.Series(rows)
    cum = s.cumsum()
    dd = (cum - cum.cummax()).min()
    wins = s[s > 0]
    losses = s[s <= 0]
    return {
        'n':   len(s),
        'win%': (s > 0).mean() * 100,
        'exp':  s.mean(),
        'avg_w': wins.mean() if not wins.empty else 0.0,
        'avg_l': losses.mean() if not losses.empty else 0.0,
        'total': s.sum(),
        'maxDD': dd,
    }


def _prep(name, days):
    pivot_tf = _PIVOT_TF_OVERRIDES.get(name, '4h')
    m15, pivot_df = oanda_fetcher.fetch(name, days=days, pivot_tf=pivot_tf)
    enriched = pivot_calculator.assign_to_m15(m15, pivot_df, pivot_tf=pivot_tf)
    cfg = FILTER_CFG_OVERRIDES.get(name)
    if cfg is not None:
        filtered = signal_detector.detect(enriched, filter_cfg=cfg)
    else:
        filtered = signal_detector.detect(enriched)          # default FILTER_CFG
    allsigs = signal_detector.detect(enriched, filter_cfg={})  # unfiltered
    return enriched, filtered, allsigs


def _run_set(label, sigs, enriched, store):
    print(f"\n  {label}  ({len(sigs)} signals)")
    print(f"    {'model':<18}{'n':>4}{'win%':>7}{'exp(pts)':>11}{'avg_w':>10}{'avg_l':>10}{'maxDD':>10}")
    for mlabel, kw in MODELS:
        results = [psim.simulate(s, enriched, **kw) for s in sigs]
        m = _metrics(results)
        store.setdefault(mlabel, []).extend(
            [r.total_pnl for r in results if r.leg1 and r.leg2]
        )
        if m is None:
            print(f"    {mlabel:<18}  (no completed trades)")
            continue
        print(f"    {mlabel:<18}{m['n']:>4}{m['win%']:>6.1f}%{m['exp']:>11.5f}"
              f"{m['avg_w']:>10.5f}{m['avg_l']:>10.5f}{m['maxDD']:>10.5f}")


def main():
    args = [a.upper() for a in sys.argv[1:] if not a.startswith('--')]
    days = 365
    for a in sys.argv[1:]:
        if a.startswith('--days='):
            days = int(a.split('=')[1])
    targets = [a for a in args if a in LIVE_PAIRS] or LIVE_PAIRS

    filt_store, all_store = {}, {}

    for name in targets:
        print(f"\n{'='*72}\n  {name}  (pivot={_PIVOT_TF_OVERRIDES.get(name, '4h')}, {days}d)\n{'='*72}")
        try:
            enriched, filtered, allsigs = _prep(name, days)
        except Exception as e:
            print(f"  Skipping {name}: {e}")
            continue
        _run_set('FILTERED (live strategy)', filtered, enriched, filt_store)
        _run_set('UNFILTERED (large sample)', allsigs, enriched, all_store)

    # Aggregate across all instruments
    for store_label, store in [('FILTERED — ALL PAIRS COMBINED', filt_store),
                               ('UNFILTERED — ALL PAIRS COMBINED', all_store)]:
        print(f"\n{'#'*72}\n  {store_label}\n{'#'*72}")
        print(f"    {'model':<18}{'n':>5}{'win%':>7}{'exp(pts)':>11}{'total':>11}{'maxDD':>10}")
        for mlabel, _ in MODELS:
            pnls = store.get(mlabel, [])
            if not pnls:
                continue
            s = pd.Series(pnls)
            cum = s.cumsum()
            dd = (cum - cum.cummax()).min()
            print(f"    {mlabel:<18}{len(s):>5}{(s>0).mean()*100:>6.1f}%"
                  f"{s.mean():>11.5f}{s.sum():>11.4f}{dd:>10.5f}")


if __name__ == '__main__':
    main()
