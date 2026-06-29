# Changelog

## 0.1.0

Initial release — EUR/GBP daily z-score mean-reversion, the first complementary
strategy validated under the portfolio-of-bots direction
(see `docs/research_statarb_pairs.md`).

- Strategy: z = (logP − rollmean(logP,60)) / rollstd(logP,60) on completed daily
  bars. Fade at |z| ≥ 2, exit at |z| ≤ 0.5, broker-side stop at the z ≈ 4 price.
- Daily cadence: a decision fires only on a new completed daily candle; the daemon
  wakes hourly to reconcile broker state (detect stop-outs) and refresh HA sensors.
- Runs on the **same OANDA practice account** as the MR Forex Trader add-on, but is
  fully isolated as a separate add-on/process and only ever touches `EUR_GBP`
  (instrument-filtered reads). Separate state file, logs, and MQTT topics
  (`forex_pairs/*`).
- **Defaults to `dry_run: true`** — logs/emails decisions but places no orders.
  Set `dry_run: false` to arm (practice orders).
- Sized **5,000 units** by default to limit margin contention with the MR bot's
  positions on the shared account.
