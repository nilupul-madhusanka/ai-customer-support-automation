"""Send reviewed replies through authenticated SMTP with verified STARTTLS."""

import os
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import parseaddr


def is_configured() -> bool:
    return all(os.getenv(key, "").strip() for key in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"))


def validate_address(value: str) -> str:
    """Require a single bare mailbox, excluding header injection and recipient lists."""
    value = value.strip()
    if not re.fullmatch(r"[^\s@<>,;\r\n]+@[^\s@<>,;\r\n]+\.[^\s@<>,;\r\n]+", value):
        raise ValueError("Customer email must be a single valid email address")
    return value


def send_reply(to_email: str, customer_name: str, ticket_id: str, reply: str) -> bool:
    if not is_configured():
        return False
    recipient = validate_address(to_email)
    user = os.environ["SMTP_USER"].strip()
    sender = os.getenv("SMTP_FROM", "").strip() or user
    if "\r" in sender or "\n" in sender:
        raise ValueError("Invalid SMTP_FROM")
    envelope_sender = validate_address(parseaddr(sender)[1])
    port = int(os.getenv("SMTP_PORT", "587"))
    if not 1 <= port <= 65535:
        raise ValueError("SMTP_PORT must be between 1 and 65535")
    msg = EmailMessage()
    msg["Subject"] = f"Your support request ({ticket_id})"
    msg["From"] = sender
    msg["To"] = recipient
    msg.set_content(f"Hi {customer_name},\n\n{reply}\n\nBest regards,\nSupport Team\n\nReference: {ticket_id}")
    with smtplib.SMTP(os.environ["SMTP_HOST"].strip(), port, timeout=15) as server:
        server.starttls(context=ssl.create_default_context())
        server.login(user, os.environ["SMTP_PASSWORD"])
        refused = server.send_message(msg, from_addr=envelope_sender, to_addrs=[recipient])
        if refused:
            raise smtplib.SMTPRecipientsRefused(refused)
    return True
