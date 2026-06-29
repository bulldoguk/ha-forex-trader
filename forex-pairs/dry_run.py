#!/usr/bin/env python3
"""
Dry-run: compute the live EUR/GBP daily decision against real OANDA data WITHOUT
placing any order. Validates the live signal path before deployment.

Run: uv run --with pandas --with numpy --with requests --with python-dotenv \
       python dry_run.py
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'trader'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'donchian_backtester'))
import numpy as np
import pandas as pd
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))

import fetcher                 # donchian_backtester/fetcher (OANDA daily candles)
import pairs_strategy as ps

df = fetcher.fetch('EURGBP', days=160, granularity='D')   # completed daily candles
closes = df['close']
print(f"\nEUR/GBP daily — {len(closes)} completed bars, "
      f"last close {closes.index[-1].date()} = {closes.iloc[-1]:.5f}")

# Recent z history (last 10 bars) for context
lp = np.log(closes)
mu = lp.rolling(ps.WINDOW).mean()
sd = lp.rolling(ps.WINDOW).std(ddof=1)
z  = (lp - mu) / sd
print("\n  last 10 daily z-scores:")
for ts, zz, px in zip(z.index[-10:], z.iloc[-10:], closes.iloc[-10:]):
    print(f"    {ts.date()}  px={px:.5f}  z={zz:+.2f}")

# Cross-check: strategy module must agree with the rolling series above.
z_mod, mu_mod, sd_mod = ps.compute_z(closes)
assert abs(z_mod - z.iloc[-1]) < 1e-9, (z_mod, z.iloc[-1])
print(f"\n  module z matches rolling series: {z_mod:+.4f} ✓")

for in_pos, dirn in [(False, None), (True, 'short'), (True, 'long')]:
    d = ps.decide(closes, in_position=in_pos, direction=dirn)
    label = 'FLAT' if not in_pos else f'IN {dirn.upper()}'
    extra = f"  stop={d['stop']:.5f}" if d['stop'] else ''
    print(f"  [{label:9}] -> {d['action'].upper():5}  ({d['reason']}){extra}")

print("\nNo orders placed (dry run).")
