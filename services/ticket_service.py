from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
import smtplib

from models.ticket import TicketAnalysis, validate_rows
from services.ai_service import AnalysisFailure, AnalysisResult, validate_message
from services.audit_service import record_analysis
from services.errors import ApplicationError, UserError
from services.storage import Repository
from services.email_service import is_configured, send_reply, validate_address
from services.writer_lock import serialized_write


@dataclass
class BatchResult:
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    stopped_reason: str = ""


@dataclass(frozen=True)
class DeliveryResult:
    message: str
    attempted: bool = False
    smtp_accepted: bool | None = False
    tracking_saved: bool = True
    status: str = "NOT_SENT"


@dataclass(frozen=True)
class ApprovalResult:
    approval_saved: bool | None
    delivery: DeliveryResult

    @property
    def message(self):
        prefix = "Approval saved." if self.approval_saved else "Approval status could not be confirmed."
        return f"{prefix} {self.delivery.message}"


def get_new_tickets(tickets):
    return [ticket for ticket in tickets if ticket["status"] == "NEW"]


@serialized_write
def process_new(repository: Repository, analyzer: Callable, *, limit=6,
                report: Callable[[str], None] = lambda text: None) -> BatchResult:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise UserError("Batch size must be between 1 and 100")
    rows = repository.load()
    pending = get_new_tickets(rows)[:limit]
    result = BatchResult(skipped=len(rows) - len(pending))
    for index, ticket in enumerate(pending):
        def stop(detail):
            result.stopped_reason = detail
            result.skipped += len(pending) - index
            report(detail)
            return result

        try:
            current = next((row for row in repository.load() if row["id"] == ticket["id"]), None)
        except Exception:
            return stop("SOURCE_READ_FAILED: Batch stopped. Refresh the Sheet; completed drafts remain saved.")
        if current is None or current["status"] != "NEW":
            result.skipped += 1
            continue
        model, attempts = None, ()
        try:
            validate_message(current["message"])
            generated = analyzer(current["message"])
            if isinstance(generated, AnalysisResult):
                model, attempts = generated.model, generated.attempts
                generated = generated.analysis
            analysis = TicketAnalysis.model_validate(generated)
        except Exception as exc:
            if isinstance(exc, AnalysisFailure):
                code, attempts = exc.code, exc.attempts
                safe_error = str(exc)
            elif isinstance(exc, UserError):
                code, safe_error = "INPUT_INVALID", str(exc)
            else:
                code = "ANALYSIS_FAILED"
                safe_error = "ANALYSIS_FAILED: No valid draft was produced. Check input and provider configuration before retrying."
            try:
                record_analysis(ticket["id"], attempts=attempts, outcome=code)
                if isinstance(exc, AnalysisFailure) and exc.stop_batch:
                    return stop(safe_error)
                if isinstance(exc, ApplicationError) and not isinstance(exc, (UserError, AnalysisFailure)):
                    return stop("PROVIDER_CONFIG: Check analysis configuration before restarting the batch.")
                repository.update(ticket["id"], {"status": "ERROR", "error_message": safe_error}, expected_status="NEW")
            except Exception:
                return stop("STORAGE_WRITE_FAILED: Could not save analysis outcome. Refresh the Sheet and check local audit storage before retrying.")
            result.failed += 1
            report(f"[ERROR] {ticket['id']}: {code}")
            continue
        try:
            record_analysis(ticket["id"], model=model, attempts=attempts, outcome="GENERATED")
            repository.update(ticket["id"], {
                **analysis.model_dump(), "status": "DRAFTED", "error_message": "",
                "final_reply": "", "reviewed_at": "",
            }, expected_status="NEW")
        except Exception:
            return stop("STORAGE_WRITE_FAILED: Draft save could not be confirmed. Refresh the Sheet before retrying; completed drafts remain saved.")
        result.succeeded += 1
        report(f"[OK] {ticket['id']} -> {analysis.category} / {analysis.priority}")
    return result


@serialized_write
def approve_ticket(repository: Repository, ticket_id: str, reply: str) -> ApprovalResult:
    reply = reply.strip()
    if not reply or len(reply) > 1200:
        raise UserError("Reviewed reply must contain 1 to 1200 characters")
    reviewed_at = datetime.now(timezone.utc).isoformat()
    changes = {
        "final_reply": reply, "status": "APPROVED",
        "reviewed_at": reviewed_at,
        "email_status": "NOT_SENT", "emailed_at": "", "error_message": "",
    }
    try:
        repository.update(ticket_id, changes, expected_status="DRAFTED")
    except UserError:
        raise
    except Exception:
        # A remote write can commit and then lose its response. Never assume
        # failure means no approval was saved, and never send on this path.
        try:
            saved = next((row for row in repository.load() if row["id"] == ticket_id), None)
        except Exception:
            saved = None
        if saved and all(saved.get(key) == value for key, value in changes.items()):
            return ApprovalResult(True, DeliveryResult("The saved approval was confirmed after a source error. Email was not attempted; refresh and use Send approved email."))
        if saved and saved["status"] == "DRAFTED":
            raise
        return ApprovalResult(None, DeliveryResult("Email was not attempted. Refresh the Sheet and check the saved reply before approving or sending again.", tracking_saved=False))
    # From this point approval is committed, even if any later delivery operation fails.
    try:
        delivery = send_approved_email(repository, ticket_id)
    except Exception:
        delivery = DeliveryResult("Email was not attempted because the approved record could not be checked. Refresh before sending.",
                                  tracking_saved=False)
    return ApprovalResult(True, delivery)


def delivery_preflight(ticket) -> str:
    if not ticket["customer_email"].strip():
        return "Email not sent: no customer email on file. Correct the Sheet record before sending."
    try:
        validate_address(ticket["customer_email"])
    except ValueError:
        return "Email not sent: invalid customer email. Correct the Sheet record before sending."
    if not is_configured():
        return "Email not sent: configure Gmail SMTP, then use Send approved email."
    return ""


@serialized_write
def send_approved_email(repository: Repository, ticket_id: str, *, confirm_uncertain: bool = False) -> DeliveryResult:
    matches = [row for row in repository.load() if row["id"] == ticket_id]
    if len(matches) != 1:
        raise UserError("Ticket ID must exist exactly once")
    ticket = matches[0]
    validate_rows([ticket])
    if ticket["status"] != "APPROVED":
        raise UserError("Only approved replies can be emailed")
    status = ticket["email_status"]
    if status == "SENT":
        return DeliveryResult("Email already sent; no duplicate sent.", smtp_accepted=True, status="SENT")
    if status in ("SENDING", "UNKNOWN", "") and not confirm_uncertain:
        raise UserError("Delivery is uncertain. Check Gmail Sent before confirming a retry; a duplicate is possible.")
    detail = delivery_preflight(ticket)
    if detail:
        # Never erase an uncertain state merely because current preflight fails.
        try:
            repository.update(ticket_id, {"error_message": detail}, expected_status="APPROVED", expected_email_status=status)
        except Exception:
            return DeliveryResult(detail + " Saving recovery guidance failed; refresh before retrying.", tracking_saved=False, status=status)
        return DeliveryResult(detail, status=status)
    try:
        repository.update(ticket_id, {"email_status": "SENDING", "error_message": ""},
                          expected_status="APPROVED", expected_email_status=status)
    except Exception:
        return DeliveryResult("Email was not attempted because delivery tracking could not be saved. Refresh the Sheet before retrying.",
                              tracking_saved=False, status=status)
    try:
        sent = send_reply(ticket["customer_email"], ticket["customer_name"], ticket_id, ticket["final_reply"])
    except Exception as exc:
        definite = isinstance(exc, (ValueError, smtplib.SMTPAuthenticationError,
                                    smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused,
                                    smtplib.SMTPDataError, smtplib.SMTPNotSupportedError))
        status = "FAILED" if definite else "UNKNOWN"
        if isinstance(exc, smtplib.SMTPAuthenticationError):
            detail = "Email rejected: check the Gmail user and app password before retrying."
        elif definite:
            detail = "Email rejected: check recipient, sender, port, and TLS settings before retrying."
        else:
            detail = "Email acceptance is uncertain. Check Gmail Sent before confirming a retry; a duplicate is possible."
        try:
            repository.update(ticket_id, {"email_status": status, "error_message": detail},
                              expected_status="APPROVED", expected_email_status="SENDING")
        except Exception:
            return DeliveryResult(detail + " Saving delivery status failed; treat delivery as uncertain and check Gmail Sent.",
                                  attempted=True, smtp_accepted=False if definite else None,
                                  tracking_saved=False, status="SENDING")
        return DeliveryResult(detail, attempted=True, smtp_accepted=False if definite else None, status=status)
    status = "SENT" if sent else "NOT_SENT"
    detail = "Email accepted by Gmail (SMTP); inbox delivery is not confirmed." if sent else "Email not sent: configure Gmail SMTP before retrying."
    try:
        repository.update(ticket_id, {"email_status": status,
                                     "emailed_at": datetime.now(timezone.utc).isoformat() if sent else "",
                                     "error_message": "" if sent else detail},
                          expected_status="APPROVED", expected_email_status="SENDING")
    except Exception:
        return DeliveryResult("Gmail accepted the email, but saving delivery status failed. Check Gmail Sent before retrying."
                              if sent else "Email was not sent, but saving delivery status failed. Refresh and check Gmail Sent before retrying.",
                              attempted=bool(sent), smtp_accepted=bool(sent), tracking_saved=False, status="SENDING")
    return DeliveryResult(detail, attempted=bool(sent), smtp_accepted=bool(sent), status=status)


@serialized_write
def retry_ticket(repository: Repository, ticket_id: str) -> None:
    repository.update(ticket_id, {
        "status": "NEW", "error_message": "", "category": "", "priority": "",
        "summary": "", "draft_reply": "", "final_reply": "", "reviewed_at": "",
    }, expected_status="ERROR")
