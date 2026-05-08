"""
Position monitor — checks open trade against TP1/TP2/SL and acts accordingly.
Called every MONITOR_INTERVAL seconds by the daemon.
Returns one of: 'tp1_hit', 'tp2_hit', 'sl_hit', 'open', 'error'
"""

VERSION = "1.6.5"

import traceback
import oanda_client
import notifier
import logger
import state as _state
import config
import scanner


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
        close_price  = float(trade.get('averageClosePrice', st['entry_price']))
        close_reason = trade_state  # 'CLOSED', etc.
        return _handle_close(st, close_price, close_reason, instrument_key)

    current_price = float(trade.get('price', st['entry_price']))

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


def _handle_tp1(st: dict, price: float, trade: dict,
                instrument_key: str) -> tuple[str, dict]:
    units_partial = config.INSTRUMENTS[instrument_key]['units_partial']
    try:
        oanda_client.partial_close(st['trade_id'], units_partial)
        oanda_client.modify_sl(st['trade_id'], st['sl_after_tp1'])
    except Exception as e:
        logger.log_event('tp1_action_error', instrument=instrument_key, detail=str(e))
        notifier.error(f'TP1 execution ({instrument_key})', traceback.format_exc())
        return 'error', st

    leg1_pips = scanner.pips(
        st['entry_price'] - price if st['direction'] == 'short'
        else price - st['entry_price'],
        instrument_key,
    )
    st['tp1_hit']    = True
    st['sl_current'] = st['sl_after_tp1']

    logger.log_event('tp1_hit', instrument=instrument_key, price=price,
                     leg1_pips=leg1_pips, new_sl=st['sl_after_tp1'])
    notifier.tp1_hit(instrument_key, st['direction'], price,
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


def _handle_close(st: dict, close_price: float, reason: str,
                  instrument_key: str) -> tuple[str, dict]:
    entry    = st['entry_price']
    is_short = st['direction'] == 'short'

    def _pips(delta): return scanner.pips(delta, instrument_key)

    if st['tp1_hit']:
        leg1_pips = _pips(st['tp1'] - entry) if is_short else _pips(entry - st['tp1'])
        if is_short:
            leg2_pips = _pips(st['tp1'] - close_price)
            if close_price > st['tp1']:
                leg2_pips = -_pips(close_price - st['tp1'])
        else:
            leg2_pips = _pips(close_price - st['tp1'])
            if close_price < st['tp1']:
                leg2_pips = -_pips(st['tp1'] - close_price)
    else:
        leg1_pips = _pips(entry - close_price) if is_short else _pips(close_price - entry)
        if (is_short and close_price > entry) or (not is_short and close_price < entry):
            leg1_pips = -leg1_pips
        leg2_pips = leg1_pips

    total_pips = logger.log_trade_close(st, instrument_key, close_price,
                                        reason, leg1_pips, leg2_pips)
    notifier.trade_closed(instrument_key, st['direction'], close_price,
                          reason, total_pips, entry)
    logger.log_event('trade_closed', instrument=instrument_key,
                     price=close_price, reason=reason, total_pips=total_pips)
    return 'closed', None
