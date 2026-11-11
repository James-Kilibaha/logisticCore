"""
Kutuma email kupitia SMTP ya .env (SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM).

    from ..core import mail
    mail.send("kampuni@mfano.co.tz", "Kichwa", "Maandishi", attachments=[("risiti.pdf", pdf_bytes, "application/pdf")])

- Port 465 = SSL; nyingine (587/25) = STARTTLS.
- Haitoi kosa: inarudisha False kama SMTP haijawekwa au utumaji umeshindwa (kosa linaandikwa kwenye log).
- `send_later` inatuma nyuma (thread) ili request isisubiri SMTP.
"""
import logging
import re
import smtplib
import threading
from email.message import EmailMessage

from .. import config

logger = logging.getLogger(__name__)

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def configured() -> bool:
    return bool(config.SMTP_HOST and (config.SMTP_FROM or config.SMTP_USER))


def valid(address: str | None) -> bool:
    return bool(address and _EMAIL.match(address.strip()))


def send(to, subject: str, body: str, attachments: list[tuple[str, bytes, str]] | None = None,
         reply_to: str | None = None) -> bool:
    recipients = [a.strip() for a in ([to] if isinstance(to, str) else list(to or [])) if valid(a)]
    if not recipients or not configured():
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = config.SMTP_FROM or config.SMTP_USER
    msg["To"] = ", ".join(recipients)
    if reply_to and valid(reply_to):
        msg["Reply-To"] = reply_to
    msg.set_content(body)
    for filename, content, mime in attachments or []:
        main, _, sub = (mime or "application/octet-stream").partition("/")
        msg.add_attachment(content, maintype=main, subtype=sub or "octet-stream", filename=filename)
    try:
        if int(config.SMTP_PORT) == 465:
            with smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, timeout=20) as smtp:
                if config.SMTP_USER:
                    smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20) as smtp:
                smtp.starttls()
                if config.SMTP_USER:
                    smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
                smtp.send_message(msg)
        return True
    except Exception:
        logger.exception("Email to %s failed", recipients)
        return False


def send_later(to, subject: str, body: str, attachments: list[tuple[str, bytes, str]] | None = None) -> None:
    if not configured():
        return
    threading.Thread(target=send, args=(to, subject, body, attachments), daemon=True).start()
