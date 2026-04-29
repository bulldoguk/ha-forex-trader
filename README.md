# Forex Trader — Home Assistant Add-on

Automated pivot mean-reversion trading daemon for GBP/USD and EUR/USD.
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
| `gbpusd_units` | Position size in OANDA units (10000 = 0.1 lot) |
| `eurusd_units` | Position size in OANDA units (10000 = 0.1 lot) |

> **Note:** Gold (XAU/USD) is disabled in v1.1.0 — backtesting showed negative
> expectancy across all range buckets. It will be re-evaluated with a different
> entry model before being re-enabled.

## Dashboard

After starting the add-on, a **Forex Trader** item appears in the HA sidebar.
Click it to see live instrument status, account balance, and trade history.

## Data persistence

Logs and state are stored in `/share/forex_trader/logs/` — this persists
across add-on restarts and updates.

## Updating

When the strategy code changes:
1. Run `sync_addon.sh` from the forex project root to copy trader/ and backtester/
2. Commit and push to GitHub
3. In HA: Settings → Add-ons → Forex Trader → **Update**

---

## How it works

### Entry detection (v1.1.0 — wick-based)

The daemon scans each M15 candle close against **4H standard floor pivot levels**:

- **Short signal:** M15 candle HIGH reaches R8 (R4 in MT notation) and the
  candle CLOSES back below R8 — a wick rejection
- **Long signal:** M15 candle LOW reaches S0 (S4) and closes back above S0

A **limit order is placed at R8/S0**. If price does not return to fill it
within 1 hour (4 M15 bars), the order is cancelled.

> **v1.0 vs v1.1:** Earlier versions required two consecutive candles (close
> above R8, then close back below). This introduced a bug at 4H candle
> boundaries where pivot level shifts created false signals. The wick-based
> single-candle approach is more accurate and generates real signals only.

### Trade management (FIFO compliant)

1. One position opened at full size
2. When **TP1** (R6) is hit → partial close of 50%, trailing SL moved one
   pivot level beyond TP1
3. When **TP2** (P4) is hit → remainder closed, trade complete
4. Net outcome after TP1 is always positive regardless of TP2 result

### Filters applied

| Filter | GBP/USD | EUR/USD |
|---|---|---|
| Min range (R8/S0 → P4) | 41 pips | 41 pips |
| Session | London + NY (08–22 UTC) | London + NY (08–22 UTC) |
| Channel (LR z-score) | ≥ 0.3 std devs | ≥ 0.3 std devs |
| Fibonacci confluence | 5% tolerance | 5% tolerance |

---

## Performance expectations

Based on 1-year backtest (OANDA data, wick-based detection, all filters applied).
*v1.1.0 figures — corrected after fixing the 4H boundary detection bug.*

### Signal frequency

| Instrument | Raw signals/year | After filters | Filled trades/year |
|---|---|---|---|
| GBP/USD | 60 | 8 | ~8 |
| EUR/USD | 58 | 12 | ~12 |
| **Total** | **118** | **~20** | **~20** |

Approximately **one to two trades per month** across both instruments.

### Backtest results (1 year, filtered)

| Instrument | Trades | Win rate | Avg win | Avg loss | Expectancy |
|---|---|---|---|---|---|
| GBP/USD | 8 | **62.5%** | +83 pips | −50 pips | +33 pips/trade |
| EUR/USD | 12 | 50.0% | +61 pips | −56 pips | +3 pips/trade |

### Expected annual P&L by position size

| Position size | GBP/USD | EUR/USD | **Total** | Recommended account |
|---|---|---|---|---|
| 0.1 lot | ~$264 | ~$36 | **~$300** | $5,000 |
| 0.5 lot | ~$1,320 | ~$180 | **~$1,500** | $25,000 |
| 1.0 lot | ~$2,640 | ~$360 | **~$3,000** | $50,000 |

Target return is approximately **6% per year** at current parameters.
This will improve as filter tuning matures with more live trade data.

### Scaling milestones

| Stage | Trigger | Action |
|---|---|---|
| Demo validation | 20+ live trades, positive expectancy confirmed | Move to live account at 0.1 lot |
| Scale to 0.5 lot | 20+ live trades on live account | Increase `*_units` in add-on config |
| Scale to 1.0 lot | Consistent profitability over 6+ months | Increase `*_units` further |

At ~20 trades/year, allow **12 months** of live trading before drawing
conclusions about strategy performance.

### Important caveats

- Backtest sample sizes are small (8–12 trades per instrument)
- No spread or commission costs are modelled
- Past backtest performance does not guarantee future results
- The strategy is a mean-reversion system — it will underperform during
  strongly trending markets where R8/S0 levels are repeatedly breached
- EUR/USD expectancy is near-zero at current parameters — monitor closely
  and be prepared to disable if live results are consistently negative

## Changelog

| Version | Change |
|---|---|
| v1.1.0 | Wick-based entry detection, 41-pip min range, Gold disabled |
| v1.0.2 | Unbuffered stdout, clearer scan cycle logging |
| v1.0.1 | Fixed sys.path priority bug (trader config vs backtester config) |
| v1.0.0 | Initial release |
