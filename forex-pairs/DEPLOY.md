# Deploying the Forex Pairs (EUR/GBP) add-on

Second add-on in this repo, alongside `forex-trader`. Architecture rationale:
`projects/forex/decisions/0001-pairs-bot-separate-addon-shared-account.md`.

## 1. Build the image (push triggers GitHub Actions → GHCR)

```bash
cd <this repo>            # bulldoguk/ha-forex-trader working copy
git add forex-pairs/ .github/workflows/build.yaml
git commit -m "Add forex_pairs add-on: EUR/GBP daily z-reversion (v0.1.0)"
git push origin main
```

The matrix workflow rebuilds both add-ons and pushes
`ghcr.io/bulldoguk/{arch}-addon-forex_pairs:0.1.0`. (The MR image rebuilds too, same
version — harmless.) Confirm the Actions run is green before continuing.

## 2. Install in Home Assistant

The repo is already added (for the MR bot), so the new add-on just appears.

1. Settings → Add-ons → Add-on Store → ⋮ → **Reload** (or `ha store reload` via SSH).
2. Open **Forex Pairs (EUR/GBP)** → **Install**. Supervisor pulls the GHCR image
   (verify it pulls, not builds: `ha addons info ec9d63fe_forex_pairs` shows `build: false`).

## 3. Configure (Configuration tab)

| Option | Value |
|---|---|
| `oanda_token`, `oanda_account_id` | **same as the MR bot** (101-001-39193548-001) |
| `oanda_env` | `practice` |
| `gmail_from`, `gmail_app_password`, `notify_email` | same as MR bot |
| `mqtt_host/port/user/password` | same as MR bot |
| `eurgbp_units` | `5000` (keep small — shared-account margin) |
| `dry_run` | **`true`** to start |

## 4. Start + verify (dry-run observation)

- Start the add-on. After install it often comes up with `boot: manual` /
  `watchdog: false` — set **Start on boot** and **Watchdog** on (same as the MR add-on).
- Check the log: `VERSION=0.1.0`, `OANDA connected`, and a `daily_decision` line with the
  current z. Confirm the startup email `[EURGBP] Pairs bot started — DRY-RUN`.
- Let it run a few days. It logs `idle_check`/`daily_decision` each cycle and emails a
  `dry_run_would_enter` if z crosses ±2 — no orders placed.

## 5. Arm

When the dry-run looks right: set `dry_run: false`, restart. It now places practice market
orders (5,000 units EUR/GBP) with a broker stop at the z≈4 price. Track results in
`/share/forex_pairs/logs/pairs_trades_summary.csv` — judge the strategy from that, not NAV.

## Ops

- Status: `python3 /app/trader/pairs_trader.py --status` (or read MQTT `forex_pairs/status`).
- After manual intervention in OANDA: stop add-on → `pairs_trader.py --reset` → restart.
- Logs in `/share/forex_pairs/logs/`: `pairs_trades.jsonl`, `pairs_trades_summary.csv`,
  `pairs_state.json`.
