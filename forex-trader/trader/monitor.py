"""
Position monitor — checks open trade against TP1/TP2/SL and acts accordingly.
Called every MONITOR_INTERVAL seconds by the daemon.
Returns one of: 'tp1_hit', 'tp2_hit', 'sl_hit', 'open', 'error'
"""

VERSION = "1.10.0"

import traceback
from datetime import datetime, timezone
import oanda_client
import notifier
import logger
import state as _state
import config
import scanner


def _hours_since_fill(st: dict) -> float | None:
    """Elapsed wall-clock hours since the position was filled, or None if unknown."""
    ft = st.get('fill_time')
    if not ft:
        return None
    try:
        filled = datetime.fromisoformat(str(ft))
    except ValueError:
        return None
    if filled.tzinfo is None:
        filled = filled.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - filled).total_seconds() / 3600.0


def check_and_act(st: dict, instrument_key: str) -> tuple[str, dict]:
    """
    st: current state dict.
    Returns (event, updated_state).
    event: 'open' | 'tp1_hit' | 'closed' | 'error'
    """
    try:
        trade = oanda_client.get_trade(st['trade_id'])
    except Exception as e:
        logger.log_event('monitor_error', detail=str(e))
        return 'error', st

    trade_state = trade.get('state', '')

    # Trade already closed by broker (SL hit or TP hit on broker side)
    if trade_state != 'OPEN':
        avg_close    = float(trade.get('averageClosePrice', st['entry_price']))
        close_price  = _runner_close_price(st, avg_close, instrument_key)
        close_reason = trade_state  # 'CLOSED', etc.
        return _handle_close(st, close_price, close_reason, instrument_key)

    instrument_oanda = config.INSTRUMENTS[instrument_key]['oanda']
    try:
        current_price = oanda_client.get_current_price(instrument_oanda)
    except Exception as e:
        logger.log_event('price_fetch_error', instrument=instrument_key, detail=str(e))
        return 'error', st

    # ── Time-stop: force-close if held longer than MAX_HOLD_HOURS ─────────────
    held = _hours_since_fill(st)
    if held is not None and held >= config.MAX_HOLD_HOURS:
        try:
            oanda_client.close_trade(st['trade_id'])
        except Exception as e:
            # Market may be closed (weekend) — retry on the next monitor cycle.
            logger.log_event('time_stop_close_error', instrument=instrument_key,
                             detail=str(e))
            return 'open', st
        logger.log_event('time_stop', instrument=instrument_key,
                         price=current_price, hours_held=round(held, 1))
        return _handle_close(st, current_price, 'time_stop', instrument_key)

    # ── TP1 not yet hit ──────────────────────────────────────────────────────
    if not st['tp1_hit']:
        tp1_reached = (
            (st['direction'] == 'short' and current_price <= st['tp1']) or
            (st['direction'] == 'long'  and current_price >= st['tp1'])
        )
        if tp1_reached:
            return _handle_tp1(st, current_price, trade, instrument_key)

    # ── TP1 already hit — watching for TP2 or trailing SL ───────────────────
    else:
        tp2_reached = (
            (st['direction'] == 'short' and current_price <= st['tp2']) or
            (st['direction'] == 'long'  and current_price >= st['tp2'])
        )
        if tp2_reached:
            return _handle_tp2(st, current_price, instrument_key)

    return 'open', st


def _fill_pl(close_resp: dict) -> float | None:
    """Realized account-currency P/L booked by a (partial) close fill.

    OANDA's trade-close response carries the realized P/L of the fill in
    orderFillTransaction.pl. Returns None if the field is absent/unparseable so a
    display-only miss never breaks TP1 execution.
    """
    try:
        return float(close_resp['orderFillTransaction']['pl'])
    except (KeyError, TypeError, ValueError):
        return None


def _fill_price(close_resp: dict) -> float | None:
    """Price a (partial) close fill actually executed at.

    The daemon decides to take TP1 off a polled mid price, but the partial closes
    at the broker's bid/ask a moment later. Measuring leg 1 against the polled
    price overstates it by the spread — the 2026-07-31 USD/CAD TP1 logged 30.5
    pips ($10.87 implied) against $10.48 actually realized. Returns None if the
    field is absent so a miss falls back to the polled price rather than failing.
    """
    try:
        return float(close_resp['orderFillTransaction']['price'])
    except (KeyError, TypeError, ValueError):
        return None


def _handle_tp1(st: dict, price: float, trade: dict,
                instrument_key: str) -> tuple[str, dict]:
    units_partial = config.INSTRUMENTS[instrument_key]['units_partial']
    try:
        close_resp = oanda_client.partial_close(st['trade_id'], units_partial)
        oanda_client.modify_sl(st['trade_id'], st['sl_after_tp1'])
    except Exception as e:
        logger.log_event('tp1_action_error', instrument=instrument_key, detail=str(e))
        notifier.error(f'TP1 execution ({instrument_key})', traceback.format_exc())
        return 'error', st

    # Measure the leg against what the partial actually filled at, not the polled
    # price that triggered it. Falls back to the polled price if OANDA's response
    # omits it.
    fill_price = _fill_price(close_resp) or price
    leg1_pips  = _leg_pips(st['entry_price'], fill_price,
                           st['direction'] == 'short', instrument_key)
    # Dollars realized on the TP1 leg — the amount that leaves unrealizedPL and
    # lands in Balance. Persist it (and the leg pips) so the dashboard can show
    # "Locked P&L" instead of the partial looking like it vanished.
    realized_pl = _fill_pl(close_resp)

    st['tp1_hit']          = True
    st['sl_current']       = st['sl_after_tp1']
    st['tp1_realized_pl']  = realized_pl
    st['leg1_pips']        = leg1_pips
    st['tp1_price_actual'] = fill_price

    logger.log_event('tp1_hit', instrument=instrument_key, price=fill_price,
                     trigger_price=price, leg1_pips=leg1_pips,
                     realized_pl=realized_pl, new_sl=st['sl_after_tp1'])
    notifier.tp1_hit(instrument_key, st['direction'], fill_price,
                     units_partial, st['sl_after_tp1'], st['tp2'], leg1_pips)
    return 'tp1_hit', st


def _handle_tp2(st: dict, price: float, instrument_key: str) -> tuple[str, dict]:
    try:
        oanda_client.close_trade(st['trade_id'])
    except Exception as e:
        logger.log_event('tp2_close_error', instrument=instrument_key, detail=str(e))
        notifier.error(f'TP2 close ({instrument_key})', traceback.format_exc())
        return 'error', st

    return _handle_close(st, price, 'tp2', instrument_key)


def _leg_pips(entry: float, exit_price: float, is_short: bool,
              instrument_key: str) -> float:
    """Signed P&L in pips for one leg, entry → exit.

    scanner.pips() returns an unsigned magnitude, so direction sets the sign here.
    Previously each call site re-derived the sign by hand and one of them had it
    inverted — the arithmetic only looked right because the magnitude was absolute.
    """
    delta = entry - exit_price if is_short else exit_price - entry
    return scanner.pips(delta, instrument_key) * (-1 if delta < 0 else 1)


def _runner_close_price(st: dict, avg_close_price: float,
                        instrument_key: str) -> float:
    """Recover the runner leg's own exit price from OANDA's averageClosePrice.

    averageClosePrice is the size-weighted average of EVERY closing fill on the
    trade — including the TP1 partial. Treating it as the runner's exit blends the
    two legs together and understates the trade (USD/CAD 2026-07-31: reported
    1.40216, true runner exit 1.40142 at the trailed stop).

    Only applies to broker-side closes. The TP2 and time-stop paths already pass a
    genuine leg-2 price, so they must not be re-derived.
    """
    if not st.get('tp1_hit'):
        return avg_close_price
    tp1_price = st.get('tp1_price_actual')
    if tp1_price is None:
        return avg_close_price   # state written before v1.9.2 — no better estimate
    cfg        = config.INSTRUMENTS[instrument_key]
    units_leg1 = cfg['units_partial']
    units_leg2 = cfg['units_total'] - cfg['units_partial']
    if units_leg2 <= 0:
        return avg_close_price
    total = avg_close_price * (units_leg1 + units_leg2) - tp1_price * units_leg1
    return total / units_leg2


def _handle_close(st: dict, close_price: float, reason: str,
                  instrument_key: str) -> tuple[str, dict]:
    """close_price must be the RUNNER leg's exit price, not a whole-trade average."""
    entry    = st['entry_price']
    is_short = st['direction'] == 'short'

    if st['tp1_hit']:
        # Leg 1 was measured against the actual TP1 fill when it executed and
        # stored then — reuse it rather than re-deriving from the theoretical tp1
        # level, which ignores the price we really got.
        leg1_pips = st.get('leg1_pips')
        if leg1_pips is None:
            leg1_pips = _leg_pips(entry, st['tp1'], is_short, instrument_key)
        # Leg 2 runs entry → exit like any other position. Measuring it from tp1
        # discarded everything the runner earned up to TP1 and could log a
        # profitable runner as a loss.
        leg2_pips = _leg_pips(entry, close_price, is_short, instrument_key)
    else:
        leg1_pips = _leg_pips(entry, close_price, is_short, instrument_key)
        leg2_pips = leg1_pips

    # Leg 1 is the partial (closed at TP1); leg 2 is the remainder. Pass their
    # unit sizes so the logger can size-weight the total instead of double-counting.
    cfg           = config.INSTRUMENTS[instrument_key]
    units_leg1    = cfg['units_partial']
    units_leg2    = cfg['units_total'] - cfg['units_partial']
    total_pips = logger.log_trade_close(st, instrument_key, close_price,
                                        reason, leg1_pips, leg2_pips,
                                        units_leg1, units_leg2)
    notifier.trade_closed(instrument_key, st['direction'], close_price,
                          reason, total_pips, entry)
    logger.log_event('trade_closed', instrument=instrument_key,
                     price=close_price, reason=reason, total_pips=total_pips)
    return 'closed', None


def settle_closed_trade(st: dict, close_price: float, reason: str,
                        instrument_key: str) -> None:
    """
    Journal a trade the daemon never saw open or close.

    Reuses the normal close path so a retroactively-discovered trade is recorded
    with the same size-weighted pip maths as any other (see log_trade_close on why
    summing legs double-counts). Called by trader._resolve_vanished_order when an
    order filled and closed inside a single scan gap.
    """
    _handle_close(st, close_price, reason, instrument_key)
