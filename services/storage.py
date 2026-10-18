import os
from typing import Protocol

from models.ticket import FIELDS, validate_rows
from services.config import ConfigurationError
from services.errors import UserError


class Repository(Protocol):
    def load(self) -> list[dict[str, str]]: ...
    def update(self, ticket_id: str, changes: dict[str, str], *, expected_status: str,
               expected_email_status: str | None = None) -> None: ...


def apply_changes(rows, ticket_id, changes, expected_status, expected_email_status=None):
    if set(changes) - (set(FIELDS) - {"id", "received_at", "customer_name", "customer_email", "message"}):
        raise UserError("Updates may only change workflow fields")
    matches = [row for row in rows if row["id"] == ticket_id]
    if len(matches) != 1:
        raise UserError("Ticket ID must exist exactly once; refresh the Sheet before continuing")
    row = matches[0]
    if row["status"] != expected_status:
        raise UserError("Ticket status changed; refresh before continuing")
    if expected_email_status is not None and row["email_status"] != expected_email_status:
        raise UserError("Email status changed; refresh before continuing")
    updated = {**row, **changes}
    validate_rows([updated])
    row.update(changes)


def get_repository() -> Repository:
    if os.getenv("DATA_SOURCE", "sheets").strip().lower() != "sheets":
        raise ConfigurationError("Only Google Sheets is supported. Set DATA_SOURCE=sheets or remove DATA_SOURCE.")
    from services.sheets_service import SheetsRepository
    return SheetsRepository()
