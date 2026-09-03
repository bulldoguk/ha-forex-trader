# Changelog

## 0.3.0 (2026-09-03)

### Fixed
- **Intermittent `401 Unauthorized` from OANDA no longer aborts a cycle.** `401` is
  now retried on its own short schedule (`_RETRY_AUTH_DELAYS = [1, 3]`), counted
  separately from the existing 5xx/transport budget so neither can exhaust the other.

  This bot and the MR bot share one OANDA token by design (ADR-0001), and OANDA
  rejects one of two *concurrent* requests on the same token with 401 rather than
  429. On 2026-09-03 both add-ons were firing at :00 and the pairs bot 401'd at 09:00
  and 11:00 while succeeding at 10:00 — and the MR bot 401'd on a single instrument
  at the same instants. The token was valid throughout. See
  [[projects/forex/decisions/0005-shared-token-401-retry|ADR-0005]].

  A genuinely revoked token still raises after 2 retries (~4s), so this does not mask
  a real auth failure.

### Changed
- **The hourly cycle is now anchored to the wall clock at `:20`** instead of sleeping
  a flat `PAIRS_CHECK_INTERVAL`, and the minute is exposed as the new
  **`check_offset_mins`** add-on option (default `20`).

  A flat `time.sleep(3600)` drifts by each loop's own duration, so the bot could not
  be held clear of the MR bot's quarter-hour scans (:00/:15/:30/:45). Anchoring keeps
  it in a fixed slot indefinitely, which removes the collision rather than just
  retrying through it.

## 0.2.2 (2026-07-30)

### Fixed
- **`pairs_trader.VERSION` was left at `0.2.0` when config.yaml went to 0.2.1.** The
  startup log line is the only thing that proves the *running image* is new (add-on
  options like `units` are stored per-install and prove nothing about the image), so
  a knowingly-stale VERSION string breaks the exact check that catches a
  publish-before-update race. Now bumped in lockstep with config.yaml, matching the
  `monitor.VERSION` rule the MR add-on already follows.

## 0.2.1 (2026-07-30)

### Changed
- **Default `eurgbp_units` 5,000 → 2,600.** The validated strategy doc instructs
  *"position sizing must survive a −330 bps trade — size off this, not off the
  average."* At 5,000 units the documented worst case (−331 bps) was **$190, i.e.
  19% of a $1,000 account**; at 2,600 it is ~$99 (9.9%). Nominal z=4 stop drops
  from 7.2% to 3.7% of the account, and peak concurrent margin (MR + pairs) from
  82% to 68%.

  Cost: expected annual contribution roughly halves (~$123 → ~$64). Accepted
  because the pairs bot is a **diversifier, not a return driver** — and at ~5
  trades/yr it would take ~19 trades (~4 years) for its live record to reach
  statistical significance, so its sizing can never be justified by its own live
  results and should stay conservative. See ADR
  [[projects/forex/decisions/0004-step-up-strategy|0004]].

## 0.2.0 (2026-07-30)

Margin pre-check on the shared account — see ADR
[[projects/forex/decisions/0003-margin-budget-small-account|0003]].

### Added
- **Margin pre-check before entering** (`oanda_client.check_margin`, new option
  `margin_safety_factor`, default 1.15). Entry txn 129 (2026-07-16) was rejected by
  OANDA for `INSUFFICIENT_MARGIN` while the MR bot held a GBP_USD position, surfacing
  only as an error email. Insufficient margin now logs `signal_deferred_margin` with
  the required/available figures, making contention a countable statistic. The signal
  is deferred, not lost: the next daily bar re-decides and re-enters while |z| still
  qualifies — which is how the 07-16 block became the 07-20 fill (+78.5 bps).
- `get_margin_rate()` — live per-instrument rate, cached, falling back to the
  expensive 5% rate rather than a cheap guess.

### Fixed
- **Corrected the margin assumption in `config.py`.** The comment claimed 5,000 units
  of EUR_GBP was "~$115 margin at 50:1". EUR_GBP is a **5% / 20:1** instrument —
  5,000 units is **~$287**, 2.5× the documented figure and 29% of a $1,000 account.
  This wrong number is why the bot was believed to be margin-light on the shared
  account.

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
