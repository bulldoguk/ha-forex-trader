# Forex Trader — Home Assistant Add-on

Automated pivot mean-reversion trading daemon for GBP/USD, EUR/USD, and Gold.
Runs as a Home Assistant add-on with a built-in status dashboard.

## Installation

1. In Home Assistant, go to **Settings → Add-ons → Add-on Store**
2. Click the three-dot menu (⋮) → **Repositories**
3. Add: `https://github.com/garymyhmbiz/ha-forex-trader`
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
