from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from models.ticket import TicketAnalysis
from services.config import check_writable
from services.storage import Repository


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


def approve_ticket(repository: Repository, ticket_id: str, reply: str) -> None:
    check_writable()
    reply = reply.strip()
    if not reply or len(reply) > 1200:
        raise ValueError("Reviewed reply must contain 1 to 1200 characters")
    repository.update(ticket_id, {
        "final_reply": reply, "status": "APPROVED",
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
    }, expected_status="DRAFTED")


def retry_ticket(repository: Repository, ticket_id: str) -> None:
    check_writable()
    repository.update(ticket_id, {
        "status": "NEW", "error_message": "", "category": "", "priority": "",
        "summary": "", "draft_reply": "", "final_reply": "", "reviewed_at": "",
    }, expected_status="ERROR")
