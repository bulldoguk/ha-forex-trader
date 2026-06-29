"""
EUR/GBP daily z-score mean-reversion — the validated strategy logic.

Pure decision functions (no I/O, no credentials) so they are unit-testable and
identical to the backtest in `statarb_backtester/cross_reversion.py`:

  z = (logP - rollmean(logP, W)) / rollstd(logP, W)   on completed daily closes
  flat & z >= +entry -> SHORT ;  flat & z <= -entry -> LONG
  in position & |z| <= exit -> close (reverted)
  blow-out stop at |z| >= stop, also set broker-side as a price level.

Convention matches the backtest: the decision is made on the most recently
COMPLETED daily bar and executed at market right after (≈ next bar's open).
"""
import math
import numpy as np
import pandas as pd

# Validated parameters (research_statarb_pairs.md). Plateau-stable; do not tune
# without re-running the stress test.
WINDOW  = 60
ENTRY_Z = 2.0
EXIT_Z  = 0.5
STOP_Z  = 4.0


def compute_z(closes: pd.Series, window: int = WINDOW):
    """Return (z, mu, sd) for the latest completed close. mu/sd are in log space."""
    lp = np.log(closes.astype(float))
    if len(lp) < window:
        raise ValueError(f"need >= {window} closes, got {len(lp)}")
    mu = lp.iloc[-window:].mean()
    sd = lp.iloc[-window:].std(ddof=1)
    z  = (lp.iloc[-1] - mu) / sd
    return float(z), float(mu), float(sd)


def stop_price(mu: float, sd: float, direction: str, stop_z: float = STOP_Z) -> float:
    """Price level where z would reach ±stop_z — used for the broker-side SL.
    short faded a high z (stop above); long faded a low z (stop below)."""
    log_stop = mu + stop_z * sd if direction == 'short' else mu - stop_z * sd
    return math.exp(log_stop)


def decide(closes: pd.Series, in_position: bool, direction: str | None = None,
           window: int = WINDOW, entry_z: float = ENTRY_Z,
           exit_z: float = EXIT_Z, stop_z: float = STOP_Z) -> dict:
    """
    Decision for the latest completed daily bar.

    Returns a dict:
      {'action': 'enter'|'exit'|'hold', 'direction': 'short'|'long'|None,
       'z': float, 'mu': float, 'sd': float, 'stop': float|None, 'reason': str}
    """
    z, mu, sd = compute_z(closes, window)
    out = {'z': z, 'mu': mu, 'sd': sd, 'direction': direction,
           'stop': None, 'action': 'hold', 'reason': ''}

    if not in_position:
        if z >= entry_z:
            out.update(action='enter', direction='short', reason=f'z={z:.2f} >= {entry_z}',
                       stop=stop_price(mu, sd, 'short', stop_z))
        elif z <= -entry_z:
            out.update(action='enter', direction='long', reason=f'z={z:.2f} <= -{entry_z}',
                       stop=stop_price(mu, sd, 'long', stop_z))
        else:
            out['reason'] = f'z={z:.2f} inside ±{entry_z}'
    else:
        if abs(z) <= exit_z:
            out.update(action='exit', reason=f'|z|={abs(z):.2f} <= {exit_z} (reverted)')
        elif abs(z) >= stop_z:
            out.update(action='exit', reason=f'|z|={abs(z):.2f} >= {stop_z} (blow-out)')
        else:
            out['reason'] = f'|z|={abs(z):.2f} holding'
    return out
