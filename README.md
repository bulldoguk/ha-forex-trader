# Forex Trader — Home Assistant Add-on

Automated pivot mean-reversion trading daemon for GBP/USD, EUR/USD, and Gold.
Runs as a Home Assistant add-on with a built-in status dashboard.

## Installation

1. In Home Assistant, go to **Settings → Add-ons → Add-on Store**
2. Click the three-dot menu (⋮) → **Repositories**
3. Add: `https://github.com/bulldoguk/ha-forex-trader`
4. Find **Forex Trader** in the store and click **Install**

## Configuration

| Option | Description |
|---|---|
| `oanda_token` | Your OANDA API token (from fxTrade → My Services → Manage API Access) |
| `oanda_account_id` | Your v20 account ID (format: xxx-xxx-xxxxxxx-xxx) |
| `oanda_env` | `practice` (demo) or `live` |
| `gmail_from` | Gmail address to send notifications from |
| `gmail_app_password` | Gmail app password (16 characters, spaces optional) |
| `notify_email` | Email address to receive notifications |
| `gbpusd_enabled` | Trade GBP/USD (default: true) |
| `eurusd_enabled` | Trade EUR/USD (default: true) |
| `gold_enabled` | Trade Gold/XAU (default: true) |
| `gbpusd_units` | Position size in OANDA units (10000 = 0.1 lot) |
| `eurusd_units` | Position size in OANDA units (10000 = 0.1 lot) |
| `gold_units` | Position size in oz (2 = 2 oz) |

## Dashboard

After starting the add-on, a **Forex Trader** item appears in the HA sidebar.
Click it to see live instrument status, account balance, and trade history.

## Data persistence

Logs and state are stored in `/share/forex_trader/logs/` — this persists
across add-on restarts and updates.

## Updating

When the strategy code changes:
1. Run `sync.sh` from the forex project root to copy trader/ and backtester/
2. Commit and push to GitHub
3. In HA: Settings → Add-ons → Forex Trader → **Update**

---

## Performance expectations

Based on 1-year backtest (OANDA historical data, all filters applied).

### Signal frequency

| Instrument | Signals/year | Filled trades/year |
|---|---|---|
| GBP/USD | 4 | 3 |
| EUR/USD | 4 | 4 |
| Gold | 9 | 7 |
| **Total** | **17** | **~14** |

Approximately **one trade per month** on average, distributed unevenly.
Quiet periods of 4–6 weeks between signals are normal.

### Expected annual P&L by position size

| Position size | GBP/USD | EUR/USD | Gold | **Total** | Recommended account |
|---|---|---|---|---|---|
| 0.1 lot / 2 oz | ~$693 | ~$414 | ~$56 | **~$1,163** | $5,000 |
| 0.5 lot / 10 oz | ~$3,465 | ~$2,070 | ~$280 | **~$5,815** | $25,000 |
| 1.0 lot / 20 oz | ~$6,930 | ~$4,140 | ~$560 | **~$11,630** | $50,000 |

Target return is approximately **23% per year** at all position sizes —
scaling up increases the dollar return but not the percentage.

### Scaling milestones

| Stage | Trigger | Action |
|---|---|---|
| Demo validation | 20+ live trades, positive expectancy confirmed | Move to live account at 0.1 lot |
| Scale to 0.5 lot | 20+ live trades on the live account | Increase `*_units` in add-on config |
| Scale to 1.0 lot | Consistent profitability over 6+ months | Increase `*_units` further |

At 14 trades/year across three instruments, allow **12–18 months** of live
trading before drawing conclusions about strategy performance.

### Important caveats

- Backtest sample sizes are small (3–7 trades per instrument)
- No spread or commission costs are modelled
- Past backtest performance does not guarantee future results
- The strategy is a mean-reversion system — it will underperform during
  strongly trending markets where R8/S0 levels are repeatedly breached
