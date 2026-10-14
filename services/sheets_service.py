import os

from models.ticket import FIELDS, LEGACY_FIELDS, validate_rows
from services.config import ConfigurationError, project_path
from services.storage import apply_changes


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
        self.values = service.spreadsheets().values()

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
            raise ValueError(f"Sheet headers must match the expected 15 columns in order. {detail} See docs/email_setup.md")
        self.legacy_headers = values[0] == LEGACY_FIELDS
        indexed = []
        for number, cells in enumerate(values[1:], start=2):
            if not cells or all(cell == "" for cell in cells):
                continue
            if len(cells) > len(FIELDS):
                raise ValueError("Sheet row has extra columns")
            indexed.append((number, dict(zip(FIELDS, [str(v) for v in cells] + [""] * (len(FIELDS) - len(cells))))))
        validate_rows([row for _, row in indexed])
        return indexed

    def load(self):
        return [row for _, row in self._read()]

    def update(self, ticket_id, changes, *, expected_status):
        indexed = self._read()
        if self.legacy_headers:
            raise ConfigurationError("Add email_status in N1 and emailed_at in O1 of Inquiries before updating tickets. See docs/email_setup.md")
        rows = [row for _, row in indexed]
        apply_changes(rows, ticket_id, changes, expected_status)
        number, row = next((number, row) for number, row in indexed if row["id"] == ticket_id)
        self.values.update(
            spreadsheetId=self.sheet_id, range=f"Inquiries!A{number}:O{number}",
            valueInputOption="RAW", body={"values": [[row[field] for field in FIELDS]]},
        ).execute()
