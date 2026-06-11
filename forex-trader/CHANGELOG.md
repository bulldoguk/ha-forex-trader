# Changelog

## v1.6.10 (2026-06-11)

### Added
- **Max concurrent positions cap**: New signals are silently discarded when 2 or more
  instruments are already pending or filled. Prevents margin pressure on small accounts
  from the unlikely-but-possible multi-instrument simultaneous signal scenario.
  Configured via `MAX_CONCURRENT_POSITIONS = 2` in `config.py`.

## v1.6.9 (2026-06-11)

### Fixed
- **TP1/TP2 never triggered (critical)**: `monitor.py` was reading `trade['price']` from
  the Oanda trade object to determine current price. That field is the *fill price*, not
  the live market price — so the TP conditions were permanently stuck at entry and would
  never fire. Fixed by fetching live price via `get_current_price()` before each TP check.

## v1.6.8 (2026-05-13)

### Fixed
- **Trade history not showing**: Dashboard history section only scanned the last 120 lines
  of `trades.jsonl`, so completed trades older than ~30 hours of scan entries were silently
  excluded. Now scans the full log for `trade_close` events.
- **Open P&L stuck on mobile tile**: MQTT account data (`unrealizedPL`) was only published
  at startup and between scan cycles — never during active position monitoring. The monitoring
  loop now fetches a fresh account summary and publishes it every 60 seconds while a trade
  is open.

## v1.6.7 (2026-05-11)

### Fixed
- **Email storm (critical)**: `scanner.latest_signal()` was called in `_handle_idle()`
  without any exception protection. Any OANDA API error (timeout, 5xx) during a scan
  escaped to the outer daemon loop handler, which sent an error email and retried after
  60 seconds — creating an email every minute until the API recovered. Fixed by wrapping
  the scanner call in its own try/except that logs and skips the scan gracefully.
- **Error rate-limiting**: Added a 1-hour cooldown to `notifier.error()` so that even
  if an exception does reach the outer handler repeatedly, only the first email per
  context per hour is sent. Subsequent suppressions are logged to stdout.
- **OANDA_ENV ignored**: `OANDA_BASE_URL` was hardcoded to `api-fxpractice.oanda.com`
  even when the add-on option `oanda_env` was set to `live`. Config now reads the
  `OANDA_ENV` environment variable (exported by `run.sh`) to select the correct URL.
- **LOG_DIR ignored**: State and log files were written to `/app/logs/` inside the
  container instead of `/share/forex_trader/logs` (the persistent path set by `run.sh`),
  causing state loss on every container restart. Config now reads `LOG_DIR` from
  the environment.

---

## v1.6.6 (2026-05-08)

### Fixed
- Docker layer cache was not being busted on version bumps, causing HA to run
  stale Python files even after updating the add-on. Added `ARG ADDON_VERSION`
  to the Dockerfile immediately before `COPY trader/`, which forces Docker to
  rebuild all subsequent layers on every version change.

---

## v1.6.5 (2026-05-07)

### Fixed
- Added `VERSION` constant to `monitor.py` to ensure the file is always
  changed on a release, giving Docker a reliable signal to invalidate the
  cached `trader/` layer. Also logs `monitor.VERSION` at daemon startup for
  easier version verification in HA logs.

---

## v1.6.4 (2026-05-07)

### Fixed
- Re-applied the `_handle_close` / `instrument_key` fix from v1.5.4 after
  sync drift during the v1.6.0 MQTT work silently reverted `monitor.py` to
  the pre-fix version.

---

## v1.6.3 (2026-05-07)

### Changed
- Merged `mqtt_publisher` module into the root `trader.py` to eliminate the
  sync-drift risk that caused the v1.6.4 regression. Resolved outstanding
  file-sync inconsistencies between `trader/` and the add-on directory.

---

## v1.6.2 (2026-05-06)

### Fixed
- Corrected `panel_icon` in `config.yaml`: replaced `mdi:chart-candlestick`
  (not a valid MDI icon) with `mdi:chart-line` so the sidebar icon renders
  correctly in HA.

---

## v1.6.1 (2026-05-06)

### Fixed
- MQTT status topic was not published on daemon startup, leaving HA sensors
  in an unknown state until the first scan cycle completed.

---

## v1.6.0 (2026-05-06)

### Added
- MQTT publishing for Home Assistant sensors: account balance/NAV and
  per-instrument status are now pushed to the broker on startup and after
  every state change, enabling live HA dashboard cards and automations.

---

## v1.5.4 (2026-05-06)

### Fixed
- Broker-closed trades (SL hit, server-side TP) now log and notify correctly.
  `_handle_close` was missing the `instrument_key` argument when called from
  the broker-closed branch in `monitor.py`, causing a `TypeError` and repeated
  error alerts any time the broker closed a position externally.

---

## v1.5.3 (2026-05-03)

### Changed
- **GBP/USD** now filters signals by **Donchian trend direction**: only longs in uptrend, only shorts in downtrend (N=120 4H bars ≈ 1 month lookback)
  - 2-year backtest: win rate 57%→64%, expectancy +0.00204→+0.00301 pts/trade, max drawdown cut 84% (-0.027→-0.004)
  - Trend direction derived from 4H pivot source candles already fetched — no extra API calls

### Research (backtester only — no live changes)
- **Donchian channel breakout** tested as a standalone trend strategy on GBP/JPY, USD/JPY, EUR/USD, USD/CAD (daily bars, N=20/55, channel/ATR exits): almost all negative across 2yr window. 2025 was dominated by failed breakouts. Standalone trend-following rejected.
- **ADX filter on Donchian breakout** tested (ADX≥20, ADX≥25 at entry): no consistent improvement — ADX was already elevated at entry for many losing trades. Regime was the problem, not signal quality.
- **Donchian trend as mean-reversion filter** tested on all live pairs: positive on GBP/USD (deployed), neutral on USD/JPY, harmful on EUR/USD (cuts too many good signals), no effect on GBP/JPY (pair is weak regardless).

---

## v1.5.2 (2026-05-03)

### Added
- **USD/CAD** as a 6th live instrument using **4H pivot levels**
  - 2-year backtest: 28 filtered signals, 60.7% win rate, +0.00323 pts/trade expectancy, max DD -0.011
  - **Notch filter**: rejects 40–51 pip range (dead zone, 29% win unfiltered); keeps tight/medium (<40 pips) and very wide (>51 pips) which both carry positive edge
  - Added `notch_range_lo` / `notch_range_hi` filter support to `filters.py`

### Research (backtester only — no live changes)
- **USD/CHF** tested (2yr, 4H pivots): best bucket 38% win, +0.00104 avg. Weak edge across all range buckets — tighter-ranging safe-haven pair, strategy doesn't fit. Rejected.
- **USD/CAD weekly pivots** tested: 0% win rate across all 22 signals. Weekly extensions on CAD trend rather than revert. Not pursued.

---

## v1.5.1 (2026-05-03)

### Research (backtester only — no live changes)
- **AUD/JPY** tested (2yr, 4H pivots): near-zero expectancy (−0.030 pts/trade),
  unstable range-bucket pattern across periods. Not added to live scanner.
- **GBP/USD weekly pivots** tested (2yr, R2 entry): 16% win rate, −0.010 pts/trade.
  Weekly extensions are trend continuations, not mean-reversion setups. Not pursued.
- Added `weekly` granularity support to OANDA fetcher for future pair testing.
- Added `AUD/JPY` to OANDA instrument map (backtester only).

---

## v1.5.0 (2026-05-03)

### Added
- **EUR/JPY** as a 5th instrument using **4H pivot levels**
  - 1-year backtest: 50 filtered signals, 48% win rate, +0.107 pts/trade expectancy
  - 50-pip minimum range threshold calibrated from range-bucket analysis
  - Tokyo + London + NY session coverage (ECB/BoJ divergence driver)
  - `eurjpy_enabled` and `eurjpy_units` add-on configuration options

### Fixed
- `USDJPY_ENABLED` and `USDJPY_UNITS` were not exported in `run.sh`, meaning
  the HA UI toggle and units field had no effect (USDJPY always ran at default
  sizing). Now correctly wired.

---

## v1.4.0 (2026-05-02)

### Added
- **USD/JPY** as a 4th instrument using **daily pivot levels** (not 4H)
  - 3-year backtest: 20 filtered signals, 85% win rate, +164 pips/trade expectancy
  - Tokyo session coverage added (00:00–09:00 UTC) alongside London + NY
  - 50-pip minimum range threshold calibrated from range-bucket analysis
- `usdjpy_enabled` and `usdjpy_units` add-on configuration options

### Fixed
- Transient OANDA network errors (SSL drops, read timeouts, connection resets)
  are now silently retried with 5 → 15 → 30s back-off inside the API client.
  Previously these logged a full traceback and sent an email alert for what
  are routine practice-API blips.

---

## v1.3.0 (2026-04-29)

### Fixed
- OANDA 5xx responses (500, 502, 503, 504) are retried automatically with
  5 → 15 → 30s back-off before raising an error.

---

## v1.2.0

### Added
- **GBP/JPY** as a 3rd instrument (86-pip min range threshold, ~54% win rate)
- `gbpjpy_enabled` and `gbpjpy_units` add-on configuration options

### Removed
- Gold (XAU/USD) configuration options — negative expectancy confirmed across
  all range buckets; instrument remains disabled in code

---

## v1.1.0

### Changed
- **Wick-based entry detection** replaces two-candle close-based approach.
  A signal fires when an M15 candle wicks to R8/S0 and closes back inside
  in the same candle. Fixes a false-signal bug at 4H candle boundaries.
- Minimum range threshold recalibrated to **41 pips** (0.0041) from
  range-bucket analysis showing win rate flips positive above this level.

### Removed
- Gold (XAU/USD) disabled — backtesting shows negative expectancy across
  all range buckets with 4H pivot levels.

---

## v1.0.2

### Fixed
- Unbuffered stdout for reliable log streaming in HA add-on environment
- Clearer scan cycle log lines showing sleep target and instrument statuses

---

## v1.0.1

### Fixed
- `sys.path` priority bug: trader `config.py` was being shadowed by the
  backtester `config.py` when both directories were on the path.

---

## v1.0.0

Initial release. GBP/USD and EUR/USD with 4H pivot mean-reversion strategy,
session filter (London + NY), linear regression channel filter, and
Fibonacci confluence filter.
