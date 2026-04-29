import pandas as pd
import matplotlib.pyplot as plt
from trade_simulator import TradeResult


def summarise(results: list[TradeResult], instrument: str) -> pd.DataFrame:
    rows = []
    for r in results:
        rows.append({
            'instrument':   instrument,
            'timestamp':    r.signal.timestamp,
            'direction':    r.signal.direction,
            'entry':        r.signal.entry_price,
            'outcome':      r.outcome,
            'pnl_points':   r.total_pnl,
            'entry_range':  r.entry_range,
            'leg1_reason':  r.leg1.exit_reason if r.leg1 else None,
            'leg2_reason':  r.leg2.exit_reason if r.leg2 else None,
        })
    return pd.DataFrame(rows)


def print_report(df: pd.DataFrame, instrument: str):
    if df.empty or 'outcome' not in df.columns:
        print(f"\n{instrument}: no signals in period.")
        return
    closed = df[df['outcome'] != 'incomplete']
    if closed.empty:
        print(f"\n{instrument}: no completed trades in period.")
        return

    total      = len(closed)
    wins       = closed[closed['pnl_points'] > 0]
    losses     = closed[closed['pnl_points'] <= 0]
    win_rate   = len(wins) / total * 100
    avg_win    = wins['pnl_points'].mean() if not wins.empty else 0
    avg_loss   = losses['pnl_points'].mean() if not losses.empty else 0
    expectancy = closed['pnl_points'].mean()

    cumulative = closed['pnl_points'].cumsum()
    peak       = cumulative.cummax()
    drawdown   = (cumulative - peak).min()

    print(f"\n{'='*50}")
    print(f"  {instrument}  —  {total} trades  ({closed['timestamp'].min().date()} to {closed['timestamp'].max().date()})")
    print(f"{'='*50}")
    print(f"  Win rate:      {win_rate:.1f}%")
    print(f"  Avg win:       {avg_win:+.5f} pts")
    print(f"  Avg loss:      {avg_loss:+.5f} pts")
    print(f"  Expectancy:    {expectancy:+.5f} pts/trade")
    print(f"  Max drawdown:  {drawdown:.5f} pts")
    print(f"\n  Outcomes:")
    for outcome, count in closed['outcome'].value_counts().items():
        print(f"    {outcome:<15} {count:>4}  ({count/total*100:.1f}%)")

    print(f"\n  Entry range analysis (R8/S0 → P4 distance):")
    for label, grp in _range_buckets(closed):
        wr = (grp['pnl_points'] > 0).mean() * 100
        n  = len(grp)
        print(f"    {label:<20} n={n:>3}  win={wr:.0f}%  avg={grp['pnl_points'].mean():+.5f}")


def _range_buckets(df: pd.DataFrame):
    q1, q2, q3 = df['entry_range'].quantile([0.25, 0.50, 0.75])
    buckets = [
        (f"tight  (<{q1:.4f})",   df[df['entry_range'] <  q1]),
        (f"medium ({q1:.4f}-{q2:.4f})", df[(df['entry_range'] >= q1) & (df['entry_range'] < q2)]),
        (f"wide   ({q2:.4f}-{q3:.4f})", df[(df['entry_range'] >= q2) & (df['entry_range'] < q3)]),
        (f"very wide (>{q3:.4f})", df[df['entry_range'] >= q3]),
    ]
    return buckets


def plot_equity(df: pd.DataFrame, instrument: str):
    closed = df[df['outcome'] != 'incomplete'].copy()
    if closed.empty:
        return
    closed = closed.sort_values('timestamp')
    closed['cumulative_pnl'] = closed['pnl_points'].cumsum()

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 7), sharex=True)

    ax1.plot(closed['timestamp'], closed['cumulative_pnl'], linewidth=1.5)
    ax1.axhline(0, color='grey', linewidth=0.5, linestyle='--')
    ax1.set_title(f'{instrument} — Equity Curve')
    ax1.set_ylabel('Cumulative PnL (pts)')

    colours = closed['pnl_points'].apply(lambda x: 'green' if x > 0 else 'red')
    ax2.bar(closed['timestamp'], closed['pnl_points'], color=colours, width=0.01)
    ax2.axhline(0, color='grey', linewidth=0.5, linestyle='--')
    ax2.set_ylabel('PnL per trade (pts)')
    ax2.set_xlabel('Date')

    plt.tight_layout()
    path = f'results_{instrument}.png'
    plt.savefig(path, dpi=150)
    print(f"  Chart saved: {path}")
    plt.close()
