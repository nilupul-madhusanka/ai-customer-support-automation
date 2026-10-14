import csv
import os
import tempfile
from pathlib import Path
from typing import Protocol

from models.ticket import FIELDS, LEGACY_FIELDS, validate_rows
from services.config import ConfigurationError, ROOT, project_path


class Repository(Protocol):
    def load(self) -> list[dict[str, str]]: ...
    def update(self, ticket_id: str, changes: dict[str, str], *, expected_status: str) -> None: ...


def apply_changes(rows, ticket_id, changes, expected_status):
    if set(changes) - (set(FIELDS) - {"id", "received_at", "customer_name", "customer_email", "message"}):
        raise ValueError("Updates may only change workflow fields")
    matches = [row for row in rows if row["id"] == ticket_id]
    if len(matches) != 1:
        raise ValueError("Ticket ID must exist exactly once")
    row = matches[0]
    if row["status"] != expected_status:
        raise ValueError("Ticket status changed; refresh before continuing")
    row.update(changes)
    validate_rows(rows)


class CsvRepository:
    """Atomic file replacement; requires one writer at a time."""

    def __init__(self, path: Path):
        self.path = path

    def load(self):
        with self.path.open(encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            if reader.fieldnames not in (FIELDS, LEGACY_FIELDS):
                raise ValueError(f"CSV headers must match the expected {len(FIELDS)} columns in order")
            rows = list(reader)
            if reader.fieldnames == LEGACY_FIELDS:
                for row in rows:
                    row.update(email_status="", emailed_at="")
            return validate_rows(rows)

    def update(self, ticket_id, changes, *, expected_status):
        rows = self.load()
        apply_changes(rows, ticket_id, changes, expected_status)
        self.write(rows)

    def write(self, rows):
        validate_rows(rows)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="", dir=self.path.parent,
                suffix=".tmp", delete=False,
            ) as file:
                temporary = Path(file.name)
                writer = csv.DictWriter(file, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerows(rows)
                file.flush()
                os.fsync(file.fileno())
            temporary.replace(self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def get_repository(*, offline=False) -> Repository:
    if offline:
        repository = CsvRepository(ROOT / "data/demo_tickets.csv")
    else:
        source = os.getenv("DATA_SOURCE", "csv").lower()
        if source == "sheets":
            from services.sheets_service import SheetsRepository
            return SheetsRepository()
        if source != "csv":
            raise ConfigurationError("DATA_SOURCE must be csv or sheets")
        repository = CsvRepository(project_path(os.getenv("CSV_PATH", "data/tickets.csv")))
    if not repository.path.exists():
        repository.write(CsvRepository(ROOT / "data/sample_inquiries.csv").load())
    return repository
