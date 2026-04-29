"""
Add-on entrypoint — starts the Flask web UI in a background thread
then runs the trading daemon in the main thread.
"""

import sys, os, threading

# Wire up paths before importing anything else
sys.path.insert(0, '/app/backtester')
sys.path.insert(0, '/app/trader')    # trader first — its config.py takes priority

# Patch config to read env-var overrides for instrument toggles/sizing
import config as _cfg

def _apply_env_overrides():
    for key in list(_cfg.INSTRUMENTS.keys()):
        enabled_var = f'{key}_ENABLED'
        units_var   = f'{key}_UNITS'
        if os.environ.get(enabled_var, 'true').lower() == 'false':
            del _cfg.INSTRUMENTS[key]
            continue
        units = int(os.environ.get(units_var, _cfg.INSTRUMENTS[key]['units_total']))
        _cfg.INSTRUMENTS[key]['units_total']   = units
        _cfg.INSTRUMENTS[key]['units_partial'] = units // 2

_apply_env_overrides()

import webapp
import trader
import notifier

if __name__ == '__main__':
    web_thread = threading.Thread(target=webapp.run_server, daemon=True, name='webapp')
    web_thread.start()
    print('[entrypoint] Web UI started on port 5000')
    notifier.startup(list(_cfg.INSTRUMENTS.keys()))
    trader.run()
