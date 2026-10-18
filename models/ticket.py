from typing import Literal
from datetime import datetime, date
import re

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from services.errors import SourceValidationError

CATEGORIES = ("Billing", "Technical Support", "Sales", "General")
PRIORITIES = ("Low", "Medium", "High")
STATUSES = ("NEW", "DRAFTED", "APPROVED", "ERROR")
FIELDS = [
    "id", "received_at", "customer_name", "customer_email", "message", "status", "category",
    "priority", "summary", "draft_reply", "final_reply", "reviewed_at", "error_message",
    "email_status", "emailed_at",
]
LEGACY_FIELDS = FIELDS[:-2]
EMAIL_STATUSES = ("", "NOT_SENT", "SENDING", "SENT", "FAILED", "UNKNOWN")


class TicketAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, strict=True)
    category: Literal["Billing", "Technical Support", "Sales", "General"]
    priority: Literal["Low", "Medium", "High"]
    summary: str = Field(min_length=5, max_length=250)
    draft_reply: str = Field(min_length=10, max_length=1200)


class StoredTicket(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(min_length=1, max_length=128)
    received_at: str
    customer_name: str
    customer_email: str
    message: str
    status: Literal["NEW", "DRAFTED", "APPROVED", "ERROR"]
    category: str
    priority: str
    summary: str
    draft_reply: str
    final_reply: str = Field(max_length=1200)
    reviewed_at: str
    error_message: str
    email_status: Literal["", "NOT_SENT", "SENDING", "SENT", "FAILED", "UNKNOWN"]
    emailed_at: str

    @field_validator("id")
    @classmethod
    def safe_id(cls, value):
        if value != value.strip() or any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("Invalid ID")
        return value

    @field_validator("received_at", "reviewed_at", "emailed_at")
    @classmethod
    def timestamp(cls, value, info):
        if not value:
            if info.field_name == "received_at":
                raise ValueError("Received time is required")
            return value
        # Date-only received times from earlier Sheets are readable; all new
        # intake and workflow times must use ISO timestamps with timezone.
        if info.field_name == "received_at" and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            date.fromisoformat(value)
            return value
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("Timezone is required")
        return value

    @model_validator(mode="after")
    def workflow_state(self):
        if self.status in ("DRAFTED", "APPROVED"):
            TicketAnalysis.model_validate({key: getattr(self, key) for key in TicketAnalysis.model_fields})
        if self.status == "APPROVED":
            if not self.final_reply.strip() or not self.reviewed_at:
                raise ValueError("Approval requires a final reply and review time")
        elif self.final_reply or self.reviewed_at or self.email_status or self.emailed_at:
            raise ValueError("Only approved tickets may have review or delivery records")
        if self.email_status == "SENT":
            if not self.emailed_at:
                raise ValueError("SMTP acceptance requires a timestamp")
        elif self.emailed_at:
            raise ValueError("Only SENT may have an email timestamp")
        return self


def validate_rows(rows: list[dict[str, str]], *, row_numbers=None) -> list[dict[str, str]]:
    seen = set()
    for number, row in enumerate(rows, start=1):
        location = f"Sheet row {row_numbers[number - 1]}" if row_numbers is not None else f"Inquiry record {number}"
        try:
            ticket = StoredTicket.model_validate(row)
        except ValidationError as exc:
            fields = sorted({str(error["loc"][0]) for error in exc.errors(include_input=False)
                             if error["loc"] and error["loc"][0] in FIELDS})
            detail = ", ".join(fields) if fields else "review, analysis, or delivery fields"
            if fields == ["received_at"]:
                recovery = "Use an ISO received time such as 2026-10-18T09:00:00+05:30, or a legacy ISO local time with a valid spreadsheet timezone."
            elif fields and set(fields) <= {"reviewed_at", "emailed_at"}:
                recovery = "Review/email times must be ISO timestamps with an explicit timezone."
            else:
                recovery = "Review times need a timezone and approved final replies allow 1–1200 characters."
            raise SourceValidationError(
                f"{location} has invalid {detail}. {recovery} Correct the Sheet record before continuing."
            ) from None
        if ticket.id in seen:
            raise SourceValidationError(f"{location} has a duplicate ID. Give every inquiry a unique ID before continuing.")
        seen.add(ticket.id)
    return rows
