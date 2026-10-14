from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
import smtplib

from models.ticket import TicketAnalysis
from services.config import check_writable
from services.storage import Repository
from services.email_service import is_configured, send_reply, validate_address


@dataclass
class BatchResult:
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0


def get_new_tickets(tickets):
    return [ticket for ticket in tickets if ticket["status"] == "NEW"]


def process_new(repository: Repository, analyzer: Callable[[str], TicketAnalysis], *, limit=6,
                report: Callable[[str], None] = lambda text: None) -> BatchResult:
    check_writable()
    if limit < 1 or limit > 100:
        raise ValueError("Batch size must be between 1 and 100")
    rows = repository.load()
    pending = get_new_tickets(rows)[:limit]
    result = BatchResult(skipped=len(rows) - len(pending))
    for ticket in pending:
        # Recheck just before calling the analyzer. This is not a concurrency lock.
        current = next(row for row in repository.load() if row["id"] == ticket["id"])
        if current["status"] != "NEW":
            result.skipped += 1
            continue
        try:
            analysis = TicketAnalysis.model_validate(analyzer(current["message"]))
        except Exception as exc:
            # Never persist raw provider payloads or messages that may include secrets.
            safe_error = f"{type(exc).__name__}: analysis failed; check configuration, input, and provider availability."
            repository.update(ticket["id"], {"status": "ERROR", "error_message": safe_error}, expected_status="NEW")
            result.failed += 1
            report(f"[ERROR] {ticket['id']}: {type(exc).__name__}")
            continue
        # Storage failures abort the batch; do not mislabel a save failure as an AI failure.
        repository.update(ticket["id"], {
            **analysis.model_dump(), "status": "DRAFTED", "error_message": "",
            "final_reply": "", "reviewed_at": "",
        }, expected_status="NEW")
        result.succeeded += 1
        report(f"[OK] {ticket['id']} -> {analysis.category} / {analysis.priority}")
    return result


def approve_ticket(repository: Repository, ticket_id: str, reply: str, *, send_email: bool = True) -> str:
    """Approve a drafted ticket and attempt to email the response to the customer."""
    check_writable()
    reply = reply.strip()
    if not reply or len(reply) > 1200:
        raise ValueError("Reviewed reply must contain 1 to 1200 characters")
    repository.update(ticket_id, {
        "final_reply": reply, "status": "APPROVED",
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "email_status": "NOT_SENT" if send_email else "DEMO", "emailed_at": "", "error_message": "",
    }, expected_status="DRAFTED")
    if not send_email:
        return f"Approved {ticket_id}. Offline demo: no email sent."
    return f"Approved {ticket_id}. {send_approved_email(repository, ticket_id)}"


def send_approved_email(repository: Repository, ticket_id: str, *, confirm_uncertain: bool = False) -> str:
    """Send the persisted reviewed response; retries require an explicit user action.

    Requires a single writer. SMTP and storage cannot commit atomically; SENDING
    survives a crash and prevents an automatic resend of an uncertain delivery.
    """
    check_writable()
    matches = [row for row in repository.load() if row["id"] == ticket_id]
    if len(matches) != 1:
        raise ValueError("Ticket ID must exist exactly once")
    ticket = matches[0]
    if ticket["status"] != "APPROVED":
        raise ValueError("Only approved replies can be emailed")
    status = ticket["email_status"]
    if status == "DEMO":
        raise ValueError("Offline demo replies cannot be emailed")
    if status == "SENT":
        return "Email already sent; no duplicate sent."
    if status in ("SENDING", "UNKNOWN", "") and not confirm_uncertain:
        raise ValueError("Delivery is uncertain. Check Gmail Sent before confirming a retry; a duplicate is possible.")
    if not ticket["customer_email"].strip():
        return "Email not sent: no customer email on file."
    if not is_configured():
        return "Email not sent: configure Gmail SMTP, then use Send approved email."
    try:
        validate_address(ticket["customer_email"])
    except ValueError:
        repository.update(ticket_id, {"email_status": "FAILED", "error_message": "Email not sent: invalid customer email."}, expected_status="APPROVED")
        return "Email not sent: invalid customer email."
    repository.update(ticket_id, {"email_status": "SENDING", "error_message": ""}, expected_status="APPROVED")
    try:
        sent = send_reply(ticket["customer_email"], ticket["customer_name"], ticket_id, ticket["final_reply"])
    except Exception as exc:
        definite_failure = isinstance(exc, (ValueError, smtplib.SMTPAuthenticationError,
                                          smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused,
                                          smtplib.SMTPDataError, smtplib.SMTPNotSupportedError))
        status = "FAILED" if definite_failure else "UNKNOWN"
        detail = f"Email {status.lower()} ({type(exc).__name__}). Check Gmail configuration and Sent mail before retrying."
        repository.update(ticket_id, {"email_status": status, "error_message": detail}, expected_status="APPROVED")
        return detail
    if not sent:
        repository.update(ticket_id, {"email_status": "NOT_SENT"}, expected_status="APPROVED")
        return "Email not sent: SMTP is not configured."
    try:
        repository.update(ticket_id, {"email_status": "SENT", "emailed_at": datetime.now(timezone.utc).isoformat(),
                                     "error_message": ""}, expected_status="APPROVED")
    except Exception:
        return "Gmail accepted the email, but saving delivery status failed. Check Gmail Sent before retrying."
    return f"Email accepted by Gmail for {ticket['customer_email']}."


def retry_ticket(repository: Repository, ticket_id: str) -> None:
    check_writable()
    repository.update(ticket_id, {
        "status": "NEW", "error_message": "", "category": "", "priority": "",
        "summary": "", "draft_reply": "", "final_reply": "", "reviewed_at": "",
    }, expected_status="ERROR")
