"""Gmail SMTP notifications for the pairs bot. Tagged [EURGBP] so they sort
distinctly from the MR bot's emails."""
import smtplib, traceback, time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone
import config

_ERROR_COOLDOWN = 3600
_last_error: dict[str, float] = {}
_TAG = '[EURGBP]'


def _send(subject: str, body: str):
    if not (config.GMAIL_FROM and config.NOTIFY_TO):
        return
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'], msg['From'], msg['To'] = subject, config.GMAIL_FROM, config.NOTIFY_TO
        msg.attach(MIMEText(body, 'plain'))
        with smtplib.SMTP('smtp.gmail.com', 587) as s:
            s.ehlo(); s.starttls()
            s.login(config.GMAIL_FROM, config.GMAIL_PASSWORD)
            s.sendmail(config.GMAIL_FROM, config.NOTIFY_TO, msg.as_string())
    except Exception:
        print(f'[notifier] failed "{subject}":\n{traceback.format_exc()}', flush=True)


def _now(): return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')


def startup(dry_run: bool, units: int):
    mode = 'DRY-RUN (no orders)' if dry_run else 'LIVE (practice account)'
    _send(f'{_TAG} Pairs bot started — {mode}',
          f"EUR/GBP daily z-reversion bot started.\n\nMode: {mode}\nUnits: {units:,}\n\n{_now()}")


def entered(direction, entry, units, stop, z):
    _send(f'{_TAG} ENTER {direction.upper()} @ {entry:.5f}  (z={z:+.2f})',
          f"""EUR/GBP {direction.upper()} — market order filled.

Entry:     {entry:.5f}
Units:     {units:,}
Stop (z≈4): {stop:.5f}
Entry z:   {z:+.2f}

Holding until z reverts to ±0.5. {_now()}""")


def exited(direction, entry, close, reason, realized_pl, pnl_pips):
    sign = '✅' if realized_pl >= 0 else '❌'
    _send(f'{_TAG} {sign} CLOSED {pnl_pips:+.1f} pips ({reason})',
          f"""EUR/GBP {direction.upper()} closed.

Entry:      {entry:.5f}
Close:      {close:.5f}
Reason:     {reason}
P&L:        {pnl_pips:+.1f} pips  ({realized_pl:+.2f} acct)

{_now()}""")


def error(context: str, detail: str):
    now = time.time()
    if now - _last_error.get(context, 0.0) < _ERROR_COOLDOWN:
        return
    _last_error[context] = now
    _send(f'{_TAG} ERROR in {context}', f"Pairs bot error.\n\nContext: {context}\n\n{detail}\n\n{_now()}")
