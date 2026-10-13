from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CATEGORIES = ("Billing", "Technical Support", "Sales", "General")
PRIORITIES = ("Low", "Medium", "High")
STATUSES = ("NEW", "DRAFTED", "APPROVED", "ERROR")
FIELDS = [
    "id", "received_at", "customer_name", "message", "status", "category",
    "priority", "summary", "draft_reply", "final_reply", "reviewed_at", "error_message",
]


class TicketAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, strict=True)
    category: Literal["Billing", "Technical Support", "Sales", "General"]
    priority: Literal["Low", "Medium", "High"]
    summary: str = Field(min_length=5, max_length=250)
    draft_reply: str = Field(min_length=10, max_length=1200)


def validate_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    seen = set()
    for row in rows:
        if set(row) != set(FIELDS) or any(not isinstance(v, str) for v in row.values()):
            raise ValueError("Every ticket must have exactly 12 text fields")
        if not row["id"].strip() or row["id"] != row["id"].strip() or row["id"] in seen:
            raise ValueError("Ticket IDs must be nonempty, unique, and have no outer spaces")
        seen.add(row["id"])
        if row["status"] not in STATUSES:
            raise ValueError("Invalid ticket status")
        if row["status"] in ("DRAFTED", "APPROVED"):
            TicketAnalysis.model_validate({k: row[k] for k in TicketAnalysis.model_fields})
        if row["status"] == "APPROVED" and (not row["final_reply"].strip() or not row["reviewed_at"]):
            raise ValueError("Approved tickets require a final reply and review timestamp")
    return rows
