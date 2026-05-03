# Changelog

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
