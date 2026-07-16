"""
Flask status dashboard — served via HA Ingress on port 5000.
Shows live instrument state, account summary, and trade history.
"""

import sys, os, json, time
from datetime import datetime, timezone
from flask import Flask, jsonify, render_template_string, request

sys.path.insert(0, '/app/backtester')
sys.path.insert(0, '/app/trader')

import config
import state as _state
import oanda_client

app = Flask(__name__)

# ── HTML template ─────────────────────────────────────────────────────────────

_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="refresh" content="30">
  <title>Forex Trader</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      background: #111318; color: #e1e1e1; padding: 16px;
    }
    h1 { font-size: 1.2rem; font-weight: 600; margin-bottom: 4px; color: #fff; }
    .subtitle { font-size: 0.8rem; color: #888; margin-bottom: 16px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; margin-bottom: 20px; }
    .card {
      background: #1c2028; border-radius: 12px; padding: 16px;
      border-left: 4px solid #444;
    }
    .card.idle   { border-color: #444; }
    .card.pending { border-color: #f59e0b; }
    .card.filled  { border-color: #10b981; }
    .card-title { font-size: 0.75rem; color: #888; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 8px; }
    .card-status {
      display: inline-block; font-size: 0.7rem; font-weight: 600;
      padding: 2px 8px; border-radius: 9999px; margin-bottom: 10px;
      text-transform: uppercase; letter-spacing: 0.05em;
    }
    .status-idle    { background: #2a2a2a; color: #888; }
    .status-pending { background: #451a03; color: #f59e0b; }
    .status-filled  { background: #022c22; color: #10b981; }
    .field { display: flex; justify-content: space-between; font-size: 0.82rem; margin-bottom: 4px; }
    .field-label { color: #888; }
    .field-value { color: #e1e1e1; font-variant-numeric: tabular-nums; }
    .field-value.profit { color: #10b981; }
    .field-value.loss   { color: #ef4444; }
    .section-title { font-size: 0.85rem; font-weight: 600; color: #aaa; margin: 16px 0 8px; }
    table { width: 100%; border-collapse: collapse; font-size: 0.8rem; }
    th { text-align: left; color: #666; font-weight: 500; padding: 4px 8px;
         border-bottom: 1px solid #2a2a2a; font-size: 0.72rem; text-transform: uppercase; }
    td { padding: 6px 8px; border-bottom: 1px solid #1a1a1a; color: #ccc; }
    tr:last-child td { border-bottom: none; }
    .win  { color: #10b981; }
    .loss { color: #ef4444; }
    .account-bar {
      background: #1c2028; border-radius: 10px; padding: 12px 16px;
      display: flex; gap: 24px; margin-bottom: 16px; flex-wrap: wrap;
    }
    .account-item { font-size: 0.82rem; }
    .account-label { color: #666; font-size: 0.72rem; text-transform: uppercase; margin-bottom: 2px; }
    .account-value { color: #fff; font-weight: 600; }
    .refresh { font-size: 0.72rem; color: #555; text-align: right; margin-top: 12px; }
  </style>
</head>
<body>
  <h1>Forex Trader</h1>
  <p class="subtitle">Auto-refreshes every 30 seconds</p>

  <!-- Account summary -->
  <div class="account-bar">
    <div class="account-item">
      <div class="account-label">Balance</div>
      <div class="account-value">${{ "%.2f"|format(account.get('balance', 0)|float) }}</div>
    </div>
    <div class="account-item">
      <div class="account-label">NAV</div>
      <div class="account-value">${{ "%.2f"|format(account.get('NAV', 0)|float) }}</div>
    </div>
    <div class="account-item">
      <div class="account-label">Open P&L</div>
      <div class="account-value {{ 'profit' if account.get('unrealizedPL', 0)|float >= 0 else 'loss' }}">
        ${{ "%.2f"|format(account.get('unrealizedPL', 0)|float) }}
      </div>
    </div>
    <div class="account-item">
      <div class="account-label">Open trades</div>
      <div class="account-value">{{ account.get('openTradeCount', 0) }}</div>
    </div>
  </div>

  <!-- Instrument cards -->
  <div class="grid">
    {% for key, st in state.items() %}
    <div class="card {{ st.status }}">
      <div class="card-title">{{ key }}</div>
      <span class="card-status status-{{ st.status }}">{{ st.status }}</span>

      {% if st.status == 'filled' or st.status == 'pending' %}
      <div class="field">
        <span class="field-label">Direction</span>
        <span class="field-value">{{ st.direction|upper if st.direction else '—' }}</span>
      </div>
      <div class="field">
        <span class="field-label">Entry</span>
        <span class="field-value">{{ "%.5f"|format(st.entry_price|float) if st.entry_price else '—' }}</span>
      </div>
      {% endif %}

      {% if st.status == 'filled' %}
      <div class="field">
        <span class="field-label">TP1</span>
        <span class="field-value">{{ "%.5f"|format(st.tp1|float) if st.tp1 else '—' }}</span>
      </div>
      <div class="field">
        <span class="field-label">TP2 (P4)</span>
        <span class="field-value">{{ "%.5f"|format(st.tp2|float) if st.tp2 else '—' }}</span>
      </div>
      <div class="field">
        <span class="field-label">Stop loss</span>
        <span class="field-value">{{ "%.5f"|format(st.sl_current|float) if st.sl_current else '—' }}</span>
      </div>
      <div class="field">
        <span class="field-label">TP1 hit</span>
        <span class="field-value {{ 'profit' if st.tp1_hit else '' }}">
          {{ '✓ Yes' if st.tp1_hit else 'No' }}
        </span>
      </div>
      {% if st.tp1_hit %}
      {% set rpl = st.get('tp1_realized_pl') %}
      <div class="field">
        <span class="field-label">Locked P&amp;L</span>
        <span class="field-value {{ 'profit' if (rpl or 0)|float >= 0 else 'loss' }}">
          {% if rpl is not none %}{{ '+' if rpl|float >= 0 else '−' }}${{ "%.2f"|format(rpl|float|abs) }}{% else %}—{% endif %}
          {% if st.get('leg1_pips') is not none %}<span style="color:#888;font-size:0.75rem"> ({{ "%+.1f"|format(st.leg1_pips|float) }}p)</span>{% endif %}
        </span>
      </div>
      {% endif %}
      {% endif %}

      {% if st.fill_time %}
      <div class="field" style="margin-top:8px">
        <span class="field-label">Since</span>
        <span class="field-value" style="font-size:0.75rem">{{ st.fill_time[:16] }}</span>
      </div>
      {% endif %}
    </div>
    {% endfor %}
  </div>

  <!-- Recent trades -->
  <div class="section-title">Recent trades</div>
  {% if trades %}
  <table>
    <thead>
      <tr>
        <th>Date</th>
        <th>Instrument</th>
        <th>Dir</th>
        <th>Entry</th>
        <th>Close</th>
        <th>Reason</th>
        <th>P&L</th>
      </tr>
    </thead>
    <tbody>
      {% for t in trades %}
      {% if t.get('event') == 'trade_close' %}
      <tr>
        <td>{{ t.get('date', t.get('time',''))[:16] }}</td>
        <td>{{ t.get('instrument', '—') }}</td>
        <td>{{ t.get('direction','—')|upper }}</td>
        <td>{{ "%.5f"|format(t.get('entry_price',0)|float) }}</td>
        <td>{{ "%.5f"|format(t.get('close_price',0)|float) }}</td>
        <td>{{ t.get('close_reason','—') }}</td>
        <td class="{{ 'win' if t.get('total_pnl_pips',0)|float > 0 else 'loss' }}">
          {{ "%+.1f"|format(t.get('total_pnl_pips',0)|float) }}
        </td>
      </tr>
      {% endif %}
      {% endfor %}
    </tbody>
  </table>
  {% else %}
  <p style="color:#555; font-size:0.82rem">No completed trades yet.</p>
  {% endif %}

  <p class="refresh">Last updated: {{ now }}</p>
</body>
</html>"""


# ── Routes ────────────────────────────────────────────────────────────────────

# Short-lived cache for the account summary so the 30s dashboard auto-refresh
# doesn't fire a fresh (worst-case ~95s, retry-laden) OANDA call on every load.
# On failure we keep serving the last good value instead of a blank page.
_ACCOUNT_CACHE = {'data': {}, 'ts': 0.0}
_ACCOUNT_TTL = 20  # seconds


def _cached_account_summary() -> dict:
    now = time.monotonic()
    if now - _ACCOUNT_CACHE['ts'] < _ACCOUNT_TTL:
        return _ACCOUNT_CACHE['data']
    try:
        _ACCOUNT_CACHE['data'] = oanda_client.get_account_summary()
        _ACCOUNT_CACHE['ts'] = now
    except Exception:
        pass  # keep last good value; refresh again after TTL
    return _ACCOUNT_CACHE['data']


@app.route('/')
def dashboard():
    st = _state.load()
    account = _cached_account_summary()

    trades = _read_trades(40)

    return render_template_string(
        _HTML,
        state=st,
        account=account,
        trades=trades,
        now=datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
    )


@app.route('/api/status')
def api_status():
    return jsonify(_state.load())


@app.route('/api/account')
def api_account():
    try:
        return jsonify(oanda_client.get_account_summary())
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/trades')
def api_trades():
    return jsonify(_read_trades(50))


def _read_trades(n: int) -> list:
    path = os.path.join(config.LOG_DIR, 'trades.jsonl')
    if not os.path.exists(path):
        return []
    with open(path) as f:
        lines = f.readlines()
    trades = []
    for line in lines:
        try:
            entry = json.loads(line.strip())
            if entry.get('event') == 'trade_close':
                trades.append(entry)
        except Exception:
            pass
    return trades[-n:]


def run_server():
    # threaded=True: a slow/hung OANDA fetch on one request must not block the
    # whole dashboard (single-threaded Werkzeug was the "check supervisor logs"
    # ingress-timeout cause).
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False, threaded=True)
