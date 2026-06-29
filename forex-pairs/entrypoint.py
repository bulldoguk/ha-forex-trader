"""Add-on entrypoint — runs the EUR/GBP pairs-reversion daemon. No web UI (status
is surfaced via MQTT sensors + email); decisions are daily, so the add-on log is
the live view."""
import sys

sys.path.insert(0, '/app/trader')

import pairs_trader

if __name__ == '__main__':
    pairs_trader.run()
