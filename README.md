# Forex Trader — Home Assistant Add-ons

Automated forex trading against an OANDA account, packaged as Home Assistant add-ons. This repository holds two:

| Add-on | Strategy | Instruments |
|---|---|---|
| **Forex Trader** (`forex-trader/`) | Intraday pivot mean-reversion, with a built-in status dashboard | GBP/USD, EUR/USD, GBP/JPY, USD/CAD |
| **Forex Pairs** (`forex-pairs/`) | Daily z-score mean-reversion, run as an uncorrelated diversifier alongside the main bot | EUR/GBP |

USD/JPY and EUR/JPY were removed from Forex Trader in v1.7.0: their backtest edge turned out to be an artifact of holding trades indefinitely (see the v1.7.0 entry in the [changelog](forex-trader/CHANGELOG.md)).

Both add-ons run prebuilt multi-arch images (`amd64`, `aarch64`) published to GHCR by GitHub Actions on every push to `main`.

## Installation

1. In Home Assistant, go to **Settings → Add-ons → Add-on Store**
2. Click the three-dot menu (⋮) → **Repositories**
3. Add: `https://github.com/bulldoguk/ha-forex-trader`
4. Find **Forex Trader** (and optionally **Forex Pairs (EUR/GBP)**) in the store and click **Install**

## Configuration — Forex Trader

| Option | Description |
|---|---|
| `oanda_token` | Your OANDA API token (from fxTrade → My Services → Manage API Access) |
| `oanda_account_id` | Your v20 account ID (format: xxx-xxx-xxxxxxx-xxx) |
| `oanda_env` | `practice` (demo) or `live` |
| `gmail_from` | Gmail address to send notifications from |
| `gmail_app_password` | Gmail app password (16 characters, spaces optional) |
| `notify_email` | Email address to receive notifications |
| `mqtt_host` / `mqtt_port` / `mqtt_user` / `mqtt_password` | MQTT broker for publishing status to HA (default `core-mosquitto:1883`) |
| `gbpusd_enabled` | Trade GBP/USD (default: true) |
| `eurusd_enabled` | Trade EUR/USD (default: true) |
| `gbpjpy_enabled` | Trade GBP/JPY (default: true) |
| `usdcad_enabled` | Trade USD/CAD (default: true) |
| `gbpusd_units` | Position size in OANDA units (10000 = 0.1 lot) |
| `eurusd_units` | Position size in OANDA units (10000 = 0.1 lot) |
| `gbpjpy_units` | Position size in OANDA units (10000 = 0.1 lot) |
| `usdcad_units` | Position size in OANDA units (10000 = 0.1 lot) |
| `max_concurrent_positions` | Cap on simultaneously open trades, to limit margin pressure (1–4, default 1) |
| `margin_safety_factor` | Headroom required over the broker's margin requirement before a new order is placed (default 1.25) |
| `max_hold_hours` | Time-stop: force-close any trade still open this long after fill (1–168, default 48) |

## Configuration — Forex Pairs (EUR/GBP)

Shares the OANDA, Gmail and MQTT options above, plus:

| Option | Description |
|---|---|
| `eurgbp_units` | Position size in OANDA units |
| `margin_safety_factor` | As above (default 1.15) |
| `check_offset_mins` | Minute past each hour to run the check (default 20), keeping it clear of Forex Trader's quarter-hour scans |
| `dry_run` | Log signals without placing orders (default **true**) |

Both bots can share one OANDA account and token. See [`forex-pairs/DEPLOY.md`](forex-pairs/DEPLOY.md) for setup.

> **Note:** Gold (XAU/USD) remains disabled — backtesting showed negative
> expectancy across all range buckets.

## Dashboard

After starting the add-on, a **Forex Trader** item appears in the HA sidebar.
Click it to see live instrument status, account balance, and trade history.

## Data persistence

Logs and state are stored in `/share/forex_trader/logs/` — this persists
across add-on restarts and updates.

## Updating

1. Bump `version` in the add-on's `config.yaml` (and `monitor.VERSION` in `trader/monitor.py` to match — the startup log line `monitor.VERSION=X` is how you confirm the new image is actually running).
2. Push to `main`. GitHub Actions builds and publishes the images to GHCR.
3. **Wait for the Actions run to finish** before updating. Updating early silently reinstalls the old image while HA records the new version number.
4. In HA: Settings → Add-ons → Add-on Store → ⋮ → **Check for updates**, then **Update** the add-on. Afterwards, confirm *Start on boot* and *Watchdog* are still enabled.

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

All positions are also subject to a **time-stop**: any trade still open `max_hold_hours` after fill (default 48) is force-closed at market. It was introduced at 24h in v1.7.0 and widened to 48h in v1.10.0 after a tuning study. The strategy is intraday, so this only affects a trade that has stalled — it is the guardrail that keeps the bot from drifting into multi-day holds.

At most `max_concurrent_positions` trades are open at once, and a new order is only placed if free margin covers the requirement times `margin_safety_factor`.

---

## Performance expectations

Based on 1-year backtest (OANDA data, wick-based detection, all filters applied).
*v1.1.0 figures — corrected after fixing the 4H boundary detection bug.*

> ⚠️ **These figures have not been re-run since several later fixes:** the v1.7.1 pip double-count fix (older pip totals summed both half-size legs, roughly doubling the move), the v1.9.2/1.9.3 fill-price and TP1 journaling fixes, and the v1.10.0 change from a 24h to a 48h time-stop. Treat them as indicative only.

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
backtests and reflect the v1.7.0 24h hold cap.*

> **Removed (v1.7.0):** USD/JPY previously showed "85% win / +164 pips/trade" here.
> That was an artifact of the old backtester holding trades indefinitely — winning
> trades held a median 2.4 days. Under a realistic 1-day hold cap the edge collapses
> to ~40% win / +47 pips, and on 4H pivots USD/JPY loses outright. It (and the
> near-inactive EUR/JPY) were removed. See the v1.7.0 entry in the
> [changelog](forex-trader/CHANGELOG.md).

### Expected annual P&L by position size

| Position size | GBP/USD | EUR/USD | GBP/JPY | **Total** | Recommended account |
|---|---|---|---|---|---|
| 0.1 lot | ~$264 | ~$36 | ~$309 | **~$609** | $5,000 |
| 0.5 lot | ~$1,320 | ~$180 | ~$1,545 | **~$3,045** | $25,000 |
| 1.0 lot | ~$2,640 | ~$360 | ~$3,090 | **~$6,090** | $50,000 |

Target return is approximately **12% per year** at current parameters.

> GBP/JPY pip values are approximate (depend on live USD/JPY rate).

### Important caveats

- Backtest sample sizes are small (8–12 trades per instrument). At roughly four trades a month, it takes many months of live trading before results mean anything — size up only once live results are statistically convincing, not on account balance alone
- No spread or commission costs are modelled
- Past backtest performance does not guarantee future results
- The strategy is a mean-reversion system — it will underperform during
  strongly trending markets where R8/S0 levels are repeatedly breached
- EUR/USD expectancy is near-zero at current parameters — monitor closely
  and be prepared to disable if live results are consistently negative

## Changelog

Full version history: [Forex Trader](forex-trader/CHANGELOG.md) · [Forex Pairs](forex-pairs/CHANGELOG.md).
