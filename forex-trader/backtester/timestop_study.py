#!/usr/bin/env python3
"""
Time-stop tuning study. Three questions, prompted by live trade 125
(GBP/USD, 131.6-pip entry range, TP1 at 23h, runner cut by the 24h cap at +79.8):

  0. PREMISE CHECK: after TP1 fires the stop moves to sl_after_tp1 — is that
     always better than entry? If not, "we can't lose on the remainder" is false
     and removing the cap post-TP1 carries real risk.
  1. DIAGNOSTIC: how often does the 24h cap actually bind, and what does it cost
     (or save) versus letting the trade run?
  2. FIX: compare flat windows, uncapping after TP1, resetting the clock at TP1,
     and scaling the window by the setup's entry range.

Usage:
  python timestop_study.py                    # GBPUSD, 730d
  python timestop_study.py --days=1095
  python timestop_study.py GBPUSD USDCAD EURUSD
"""

import os
import pickle
import sys
import pandas as pd

import oanda_fetcher
import pivot_calculator
import signal_detector
import timestop_simulator as tsim
from config import FILTER_CFG_OVERRIDES

LIVE_PAIRS = ['GBPUSD', 'EURUSD', 'GBPJPY', 'USDCAD']
_PIVOT_TF_OVERRIDES = {'USDJPY': 'daily'}
PIP = {'GBPUSD': 0.0001, 'EURUSD': 0.0001, 'USDCAD': 0.0001,
       'GBPJPY': 0.01, 'USDJPY': 0.01, 'EURJPY': 0.01}

BARS_PER_HOUR = 4
POLICIES = [
    ('none',            'no time-stop at all'),
    ('flat:48',         'flat 12h'),
    ('flat:96',         'flat 24h  <-- LIVE'),
    ('flat:192',        'flat 48h'),
    ('flat:288',        'flat 72h'),
    ('post_tp1_free',   '24h pre-TP1, uncapped after'),
    ('reset_at_tp1',    '24h, clock resets at TP1'),
    ('range:1.0',       'scaled: 1.0 bars/pip of range'),
    ('range:2.0',       'scaled: 2.0 bars/pip of range'),
    ('range:3.0',       'scaled: 3.0 bars/pip of range'),
]


def _stats(pnls_pips):
    if not pnls_pips:
        return None
    s = pd.Series(pnls_pips)
    cum = s.cumsum()
    return dict(n=len(s), win=(s > 0).mean() * 100, exp=s.mean(),
                total=s.sum(), dd=(cum - cum.cummax()).min(),
                sd=s.std() if len(s) > 1 else 0.0)


_CACHE_DIR = os.environ.get('BACKTEST_CACHE', '/tmp/fx_candle_cache')


def _fetch_cached(name, days, pivot_tf):
    """Disk-cache the candle pull.

    A 5-year M15 history is ~125k candles per pair fetched 5,000 at a time, so an
    uncached re-run costs minutes of API paging before any simulation starts —
    which makes iterating on policy variants painful. Cache is keyed on the exact
    request; delete the directory to force a refresh.
    """
    os.makedirs(_CACHE_DIR, exist_ok=True)
    path = os.path.join(_CACHE_DIR, f'{name}_{days}_{pivot_tf}.pkl')
    if os.path.exists(path):
        with open(path, 'rb') as f:
            return pickle.load(f)
    data = oanda_fetcher.fetch(name, days=days, pivot_tf=pivot_tf)
    with open(path, 'wb') as f:
        pickle.dump(data, f)
    return data


def _prep(name, days):
    pivot_tf = _PIVOT_TF_OVERRIDES.get(name, '4h')
    m15, pivot_df = _fetch_cached(name, days, pivot_tf)
    enriched = pivot_calculator.assign_to_m15(m15, pivot_df, pivot_tf=pivot_tf)
    cfg = FILTER_CFG_OVERRIDES.get(name)
    sigs = signal_detector.detect(enriched, filter_cfg=cfg) if cfg is not None \
        else signal_detector.detect(enriched)
    # The live filters cut ~95% of raw signals, leaving too few trades to tune a
    # holding rule on. The unfiltered set is the same strategy mechanics on a much
    # larger sample — used for statistical power, not as a P&L claim.
    allsigs = signal_detector.detect(enriched, filter_cfg={})
    return enriched, sigs, allsigs


USE_ALL = False


def main():
    global USE_ALL
    args = [a.upper() for a in sys.argv[1:] if not a.startswith('--')]
    days = 730
    for a in sys.argv[1:]:
        if a.startswith('--days='):
            days = int(a.split('=')[1])
        if a == '--unfiltered':
            USE_ALL = True
    targets = [a for a in args if a in LIVE_PAIRS] or ['GBPUSD']

    pooled = {pol: [] for pol, _ in POLICIES}
    pooled_wide = {pol: [] for pol, _ in POLICIES}
    pooled_premise = []

    for name in targets:
        pip = PIP[name]
        try:
            enriched, sigs, allsigs = _prep(name, days)
        except Exception as e:
            print(f"  Skipping {name}: {e}")
            continue
        if USE_ALL:
            sigs = allsigs

        print(f"\n{'='*78}\n  {name} — {days}d, {len(sigs)} signals"
              f"{' (UNFILTERED)' if USE_ALL else ''}\n{'='*78}")

        # ── 0. Premise check ────────────────────────────────────────────────
        locked = [((s.entry_price - s.sl_after_tp1) if s.direction == 'short'
                   else (s.sl_after_tp1 - s.entry_price)) / pip for s in sigs]
        pooled_premise += locked
        ls_all = pd.Series(locked)
        ls = pd.Series(locked)
        bad = (ls <= 0).sum()
        print(f"\n  PREMISE — profit locked by sl_after_tp1 (pips vs entry):")
        print(f"    min {ls.min():+.1f}   median {ls.median():+.1f}   "
              f"max {ls.max():+.1f}")
        print(f"    setups where the trailed stop is NOT in profit: "
              f"{bad} / {len(ls)} ({100*bad/max(len(ls),1):.1f}%)")

        # Run every policy over every signal, then keep only signals that RESOLVE
        # under all of them. Comparing policies on different subsets is the trap
        # here: an uncapped policy leaves slow trades open, they get dropped as
        # incomplete, and it looks better purely by surviving a nicer sample.
        arrays = tsim.prepare(enriched)
        runs = {pol: [tsim.simulate(s, enriched, pol, pip_size=pip, arrays=arrays)
                      for s in sigs] for pol, _ in POLICIES}
        keep = [i for i in range(len(sigs))
                if all(runs[pol][i].complete for pol, _ in POLICIES)]
        dropped = len(sigs) - len(keep)
        if dropped:
            print(f"\n  ({dropped} of {len(sigs)} signals unresolved under at least "
                  f"one policy — excluded so all policies score the same trades)")
        runs = {pol: [runs[pol][i] for i in keep] for pol, _ in POLICIES}

        # ── 1. Diagnostic on the live policy ────────────────────────────────
        live = runs['flat:96']
        free = runs['none']
        bound = [r for r in live if r.capped]
        print(f"\n  DIAGNOSTIC — the live 24h cap:")
        print(f"    binds on {len(bound)} of {len(live)} trades "
              f"({100*len(bound)/max(len(live),1):.0f}%)")
        if bound:
            b_tp1 = [r for r in bound if r.tp1_hit]
            print(f"      of those, {len(b_tp1)} had already hit TP1 "
                  f"({100*len(b_tp1)/len(bound):.0f}%) — the trade-125 case")
        deltas = [(f.total_pnl - r.total_pnl) / pip
                  for r, f in zip(live, free) if r.capped]
        if deltas:
            d = pd.Series(deltas)
            print(f"    letting those run instead: mean {d.mean():+.1f} pips/trade, "
                  f"total {d.sum():+.1f}  (best {d.max():+.1f}, worst {d.min():+.1f})")

        # ── 2. Policy comparison ────────────────────────────────────────────
        print(f"\n  POLICY COMPARISON")
        print(f"    {'policy':<34}{'n':>5}{'win%':>7}{'exp(pips)':>11}"
              f"{'total':>10}{'maxDD':>10}{'capped%':>9}")
        for pol, label in POLICIES:
            rs = runs[pol]
            st = _stats([r.total_pnl / pip for r in rs])
            if not st:
                continue
            pooled[pol] += [r.total_pnl / pip for r in rs]
            pooled_wide[pol] += [r.total_pnl / pip for r in rs
                                 if abs(r.entry_range) / pip > 100]
            cap_pct = 100 * sum(1 for r in rs if r.capped) / max(len(rs), 1)
            mark = '  *' if pol == 'flat:96' else ''
            print(f"    {label:<34}{st['n']:>5}{st['win']:>6.1f}%{st['exp']:>11.2f}"
                  f"{st['total']:>10.0f}{st['dd']:>10.1f}{cap_pct:>8.0f}%{mark}")

        # ── 3. Does the range-scaled idea track reality? ─────────────────────
        wide = [r for r in live if abs(r.entry_range) / pip > 100]
        narrow = [r for r in live if abs(r.entry_range) / pip <= 100]
        print(f"\n  CAP INCIDENCE BY SETUP WIDTH (live 24h policy)")
        for label, grp in (('entry range > 100 pips', wide),
                           ('entry range <= 100 pips', narrow)):
            if grp:
                c = sum(1 for r in grp if r.capped)
                print(f"    {label:<26} n={len(grp):>4}  capped {c:>4} "
                      f"({100*c/len(grp):>3.0f}%)  "
                      f"exp={_stats([r.total_pnl/pip for r in grp])['exp']:+.2f} pips")

    # ── Pooled across every pair run ─────────────────────────────────────────
    if len(targets) > 1 or True:
        ps = pd.Series(pooled_premise)
        print(f"\n{'#'*78}\n  POOLED — {', '.join(targets)} "
              f"({'unfiltered' if USE_ALL else 'filtered'}, {days}d)\n{'#'*78}")
        print(f"  Premise: sl_after_tp1 locks min {ps.min():+.1f} / median "
              f"{ps.median():+.1f} pips; not-in-profit on {(ps<=0).sum()}/{len(ps)}")
        base = _stats(pooled['flat:96'])
        print(f"\n  {'policy':<34}{'n':>5}{'win%':>7}{'exp(pips)':>11}"
              f"{'total':>10}{'maxDD':>10}{'vs live':>9}{'t(paired)':>11}")
        live_pnl = pd.Series(pooled['flat:96'])
        for pol, label in POLICIES:
            s = _stats(pooled[pol])
            if not s:
                continue
            d = s['exp'] - base['exp']
            # Paired t on the per-trade difference: same signals, same fills, only
            # the holding rule differs, so the pairing removes nearly all the
            # variance that would otherwise swamp a sub-pip effect.
            diff = pd.Series(pooled[pol]) - live_pnl
            t = (diff.mean() / (diff.std() / len(diff) ** 0.5)) \
                if diff.std() > 0 else 0.0
            mark = '  *' if pol == 'flat:96' else ''
            print(f"  {label:<34}{s['n']:>5}{s['win']:>6.1f}%{s['exp']:>11.2f}"
                  f"{s['total']:>10.0f}{s['dd']:>10.1f}{d:>+9.2f}{t:>+11.2f}{mark}")
        print(f"  (paired t vs the live 24h policy; |t| > 2 ~ significant at 5%)")

        print(f"\n  WIDE SETUPS ONLY (entry range > 100 pips)")
        bw = _stats(pooled_wide['flat:96'])
        if bw:
            print(f"  {'policy':<34}{'n':>5}{'win%':>7}{'exp(pips)':>11}"
                  f"{'total':>10}{'vs live':>9}")
            for pol, label in POLICIES:
                s = _stats(pooled_wide[pol])
                if not s:
                    continue
                mark = '  *' if pol == 'flat:96' else ''
                print(f"  {label:<34}{s['n']:>5}{s['win']:>6.1f}%{s['exp']:>11.2f}"
                      f"{s['total']:>10.0f}{s['exp']-bw['exp']:>+9.2f}{mark}")


if __name__ == '__main__':
    main()
