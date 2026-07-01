# Forex Trader — Home Assistant Add-on

Automated pivot mean-reversion trading daemon for GBP/USD, EUR/USD, GBP/JPY, and USD/CAD.
(USD/JPY and EUR/JPY were removed in v1.7.0 — see [[projects/forex/decisions/0002-remove-usdjpy-eurjpy-holding-time-artifact|ADR 0002]].)
Runs as a Home Assistant add-on with a built-in status dashboard. Strategy detail in
[[projects/forex/docs/strategy_pivot_meanreversion|docs/strategy_pivot_meanreversion.md]];
project overview in [[projects/forex/CLAUDE|CLAUDE.md]].

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
| `gbpjpy_enabled` | Trade GBP/JPY (default: true) |
| `usdcad_enabled` | Trade USD/CAD (default: true) |
| `gbpusd_units` | Position size in OANDA units (10000 = 0.1 lot) |
| `eurusd_units` | Position size in OANDA units (10000 = 0.1 lot) |
| `gbpjpy_units` | Position size in OANDA units (10000 = 0.1 lot) |
| `usdcad_units` | Position size in OANDA units (10000 = 0.1 lot) |

> **Note:** Gold (XAU/USD) remains disabled — backtesting showed negative
> expectancy across all range buckets.

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

| Filter | GBP/USD | EUR/USD | GBP/JPY | USD/CAD |
|---|---|---|---|---|
| Min range (R8/S0 → P4) | 41 pips | 41 pips | 86 pips | notch: skip 40–51 pips |
| Session | London + NY | London + NY | London + NY | London + NY |
| Channel (LR z-score) | ≥ 0.3 std devs | ≥ 0.3 std devs | ≥ 0.3 std devs | ≥ 0.3 std devs |
| Fibonacci confluence | 5% tolerance | 5% tolerance | 5% tolerance | 5% tolerance |
| Pivot source | 4H candle | 4H candle | 4H candle | 4H candle |

All positions are also subject to a **24h time-stop** (v1.7.0): any trade still
open 24 hours after fill is force-closed at market. The strategy is intraday, so
this only ever affects a trade that has stalled — it is the guardrail that keeps
the bot from drifting into multi-day holds.

---

## Performance expectations

Based on 1-year backtest (OANDA data, wick-based detection, all filters applied).
*v1.1.0 figures — corrected after fixing the 4H boundary detection bug.*

### Signal frequency

| Instrument | Backtest window | After filters | Approx trades/year |
|---|---|---|---|
| GBP/USD | 1 year | 8 | ~8 |
| EUR/USD | 1 year | 12 | ~12 |
| GBP/JPY | 1 year | ~14 | ~13 |
| USD/CAD | 3 years | ~44 | ~15 |
| **Total** | | | **~48** |

Approximately **four trades per month** across all instruments.

### Backtest results (filtered)

| Instrument | Trades | Win rate | Avg win | Avg loss | Expectancy | Pivot |
|---|---|---|---|---|---|---|
| GBP/USD | 8 | 62.5% | +83 pips | −50 pips | +33 pips/trade | 4H |
| EUR/USD | 12 | 50.0% | +61 pips | −56 pips | +3 pips/trade | 4H |
| GBP/JPY | 13 | 54.0% | +96 pips | −53 pips | +34 pips/trade | 4H |
| USD/CAD | ~44 | ~57% | — | — | +21 pips/trade | 4H |

*GBP/JPY pip value ≈ $0.70/pip at 0.1 lot. All figures are pre-cost midpoint
backtests and now reflect the v1.7.0 hold cap.*

> **Removed (v1.7.0):** USD/JPY previously showed "85% win / +164 pips/trade" here.
> That was an artifact of the old backtester holding trades indefinitely — winning
> trades held a median 2.4 days. Under a realistic 1-day hold cap the edge collapses
> to ~40% win / +47 pips, and on 4H pivots USD/JPY loses outright. It (and the
> near-inactive EUR/JPY) were removed. See
> [[projects/forex/decisions/0002-remove-usdjpy-eurjpy-holding-time-artifact|ADR 0002]].

### Expected annual P&L by position size

| Position size | GBP/USD | EUR/USD | GBP/JPY | **Total** | Recommended account |
|---|---|---|---|---|---|
| 0.1 lot | ~$264 | ~$36 | ~$309 | **~$609** | $5,000 |
| 0.5 lot | ~$1,320 | ~$180 | ~$1,545 | **~$3,045** | $25,000 |
| 1.0 lot | ~$2,640 | ~$360 | ~$3,090 | **~$6,090** | $50,000 |

Target return is approximately **12% per year** at current parameters.

> GBP/JPY pip values are approximate (depend on live USD/JPY rate).

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

See [CHANGELOG.md](CHANGELOG.md) for full version history.
