import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from models.ticket import FIELDS, LEGACY_FIELDS, validate_rows
from services.config import ConfigurationError, project_path
from services.storage import apply_changes
from services.errors import SourceValidationError
from services.writer_lock import serialized_write


class SheetsRepository:
    """Single-writer Sheets adapter, addressing updates by stable ticket ID."""

    def __init__(self, service=None, sheet_id=None):
        self.sheet_id = sheet_id or os.getenv("GOOGLE_SHEET_ID", "")
        if not self.sheet_id:
            raise ConfigurationError("Set GOOGLE_SHEET_ID before using Sheets")
        if service is None:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
            from google_auth_httplib2 import AuthorizedHttp
            import httplib2
            path = project_path(os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "credentials/service-account.json"))
            if not path.is_file():
                raise ConfigurationError("Google service account credential file is missing")
            credentials = service_account.Credentials.from_service_account_file(
                str(path), scopes=["https://www.googleapis.com/auth/spreadsheets"],
            )
            service = build("sheets", "v4", http=AuthorizedHttp(credentials, http=httplib2.Http(timeout=30)),
                            cache_discovery=False)
        self.service = service
        self.values = service.spreadsheets().values()
        self._received_timezone = None

    def _normalize_received_at(self, value):
        """Interpret legacy ISO local datetimes in the actual spreadsheet zone.

        Date-only legacy values retain their original precision. Review/email
        timestamps remain strict: their timezone must always be explicit.
        """
        if not isinstance(value, str) or len(value) <= 10:
            return value
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value  # StoredTicket emits the safe row/field diagnostic.
        if parsed.tzinfo is not None:
            return value
        if self._received_timezone is None:
            properties = self.service.spreadsheets().get(
                spreadsheetId=self.sheet_id, fields="properties.timeZone",
            ).execute().get("properties", {})
            try:
                self._received_timezone = ZoneInfo(properties["timeZone"])
            except (KeyError, TypeError, ValueError, ZoneInfoNotFoundError):
                raise SourceValidationError("The spreadsheet timezone is missing or invalid. Set it in Google Sheets File → Settings, or give received_at an explicit timezone offset.") from None
        local = parsed.replace(tzinfo=self._received_timezone)
        alternate = local.replace(fold=1)
        # Never guess an ambiguous or nonexistent daylight-saving local time.
        roundtrip = local.astimezone(timezone.utc).astimezone(self._received_timezone).replace(tzinfo=None)
        if roundtrip != parsed or local.utcoffset() != alternate.utcoffset():
            raise SourceValidationError("A received_at time is ambiguous or nonexistent in the spreadsheet timezone. Enter the original time with an explicit timezone offset in the Sheet.")
        return local.isoformat()

    def _read(self):
        values = self.values.get(spreadsheetId=self.sheet_id, range="Inquiries!A1:P").execute().get("values", [])
        if not values or values[0] not in (FIELDS, LEGACY_FIELDS):
            headers = values[0] if values else []
            mismatch = next((index for index, field in enumerate(FIELDS)
                             if index >= len(headers) or headers[index] != field), len(FIELDS))
            if mismatch < len(FIELDS):
                column = chr(65 + mismatch)
                detail = f"{column}1 must be '{FIELDS[mismatch]}'."
                if FIELDS[mismatch] == "customer_email" and headers[mismatch:mismatch + 1] == ["message"]:
                    detail += " The customer_email column is missing before message; preserve existing data when inserting it."
            else:
                detail = "Remove unexpected headers after O1."
            raise SourceValidationError(f"Sheet headers must match the expected 15 columns in order. {detail} See docs/email_setup.md")
        self.legacy_headers = values[0] == LEGACY_FIELDS
        indexed = []
        for number, cells in enumerate(values[1:], start=2):
            if not cells or all(cell == "" for cell in cells):
                continue
            if len(cells) > len(FIELDS):
                raise SourceValidationError(f"Sheet row {number} has extra columns; keep ticket values within A:O.")
            row = dict(zip(FIELDS, [str(v) for v in cells] + [""] * (len(FIELDS) - len(cells))))
            row["received_at"] = self._normalize_received_at(row["received_at"])
            indexed.append((number, row))
        validate_rows([row for _, row in indexed], row_numbers=[number for number, _ in indexed])
        return indexed

    def load(self):
        return [row for _, row in self._read()]

    @serialized_write
    def update(self, ticket_id, changes, *, expected_status, expected_email_status=None):
        indexed = self._read()
        if self.legacy_headers:
            raise ConfigurationError("Add email_status in N1 and emailed_at in O1 of Inquiries before updating tickets. See docs/email_setup.md")
        rows = [row for _, row in indexed]
        apply_changes(rows, ticket_id, changes, expected_status, expected_email_status)
        number, row = next((number, row) for number, row in indexed if row["id"] == ticket_id)
        self.values.update(
            spreadsheetId=self.sheet_id, range=f"Inquiries!A{number}:O{number}",
            valueInputOption="RAW", body={"values": [[row[field] for field in FIELDS]]},
        ).execute()
