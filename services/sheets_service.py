import os

from models.ticket import FIELDS, validate_rows
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
        values = self.values.get(spreadsheetId=self.sheet_id, range="Inquiries!A1:M").execute().get("values", [])
        if not values or values[0] != FIELDS:
            raise ValueError("Sheet headers must match the expected 12 columns in order")
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
        rows = [row for _, row in indexed]
        apply_changes(rows, ticket_id, changes, expected_status)
        number, row = next((number, row) for number, row in indexed if row["id"] == ticket_id)
        self.values.update(
            spreadsheetId=self.sheet_id, range=f"Inquiries!A{number}:L{number}",
            valueInputOption="RAW", body={"values": [[row[field] for field in FIELDS]]},
        ).execute()
