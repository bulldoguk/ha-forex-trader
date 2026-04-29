"""Gmail SMTP notifications for all key trade events."""

import smtplib, traceback
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import config


def _send(subject: str, body: str):
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From']    = config.GMAIL_FROM
        msg['To']      = config.NOTIFY_TO
        msg.attach(MIMEText(body, 'plain'))
        with smtplib.SMTP('smtp.gmail.com', 587) as s:
            s.ehlo(); s.starttls()
            s.login(config.GMAIL_FROM, config.GMAIL_PASSWORD)
            s.sendmail(config.GMAIL_FROM, config.NOTIFY_TO, msg.as_string())
    except Exception:
        print(f'[notifier] Failed to send "{subject}":\n{traceback.format_exc()}')


def _now(): return datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')

def _tag(instrument_key: str) -> str:
    return f'[{instrument_key}]'


def signal_detected(instrument_key: str, direction: str, entry: float,
                    tp1: float, tp2: float, sl: float, entry_range: float):
    pip_unit = 'pts' if instrument_key == 'GOLD' else 'pips'
    _send(
        f'{_tag(instrument_key)} Signal: {"SHORT" if direction=="short" else "LONG"} @ {entry:.5f}',
        f"""{instrument_key} {direction.upper()} signal — limit order placed.

Entry:        {entry:.5f}
TP1:          {tp1:.5f}
TP2 (P4):     {tp2:.5f}
Stop loss:    {sl:.5f}
Range R8→P4:  {entry_range:.1f} {pip_unit}

Will notify when filled.
{_now()}"""
    )


def order_filled(instrument_key: str, direction: str, fill_price: float,
                 units: int, sl: float, tp1: float, tp2: float):
    _send(
        f'{_tag(instrument_key)} FILLED {"SHORT" if direction=="short" else "LONG"} @ {fill_price:.5f}',
        f"""{instrument_key} limit order filled.

Direction:    {direction.upper()}
Fill price:   {fill_price:.5f}
Units:        {units:,}
Stop loss:    {sl:.5f}
TP1:          {tp1:.5f}
TP2 (P4):     {tp2:.5f}

Monitoring. Will notify on TP1.
{_now()}"""
    )


def order_cancelled(instrument_key: str, reason: str):
    _send(
        f'{_tag(instrument_key)} Limit order cancelled',
        f"""{instrument_key} unfilled limit order cancelled.

Reason: {reason}
{_now()}"""
    )


def tp1_hit(instrument_key: str, direction: str, tp1_price: float,
            partial_units: int, new_sl: float, tp2: float, leg1_pips: float):
    pip_unit = 'pts' if instrument_key == 'GOLD' else 'pips'
    _send(
        f'{_tag(instrument_key)} TP1 hit @ {tp1_price:.5f} — partial close done',
        f"""{instrument_key} TP1 reached.

Closed:       {partial_units:,} units @ {tp1_price:.5f}
Leg 1 P&L:    {leg1_pips:+.1f} {pip_unit}
New SL:       {new_sl:.5f}
TP2 target:   {tp2:.5f}

Remaining {partial_units:,} units running to P4.
{_now()}"""
    )


def trade_closed(instrument_key: str, direction: str, close_price: float,
                 reason: str, total_pips: float, entry_price: float):
    pip_unit = 'pts' if instrument_key == 'GOLD' else 'pips'
    sign = '✅' if total_pips > 0 else '❌'
    _send(
        f'{_tag(instrument_key)} {sign} Closed: {total_pips:+.1f} {pip_unit} ({reason})',
        f"""{instrument_key} trade closed.

Direction:    {direction.upper()}
Entry:        {entry_price:.5f}
Close:        {close_price:.5f}
Reason:       {reason}
Total P&L:    {total_pips:+.1f} {pip_unit}

{_now()}"""
    )


def error(context: str, detail: str):
    _send(
        f'[TRADER] ERROR in {context}',
        f"""Error in trading daemon.

Context: {context}

{detail}

{_now()}"""
    )
