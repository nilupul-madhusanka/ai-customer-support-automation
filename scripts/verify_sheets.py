"""Initialize an empty demo Sheet and verify the project's live repository.

Run from the project root: python -m scripts.verify_sheets --initialize
"""
import argparse

from dotenv import set_key
from googleapiclient.discovery import build

from models.ticket import FIELDS
from services.ai_service import analyze_inquiry
from services.config import ROOT
from services.sheets_service import SheetsRepository
from services.storage import CsvRepository
from services.ticket_service import process_new, retry_ticket


def initialize(repository, service):
    sheets = service.spreadsheets().get(
        spreadsheetId=repository.sheet_id, fields="sheets.properties",
    ).execute()["sheets"]
    target = next((sheet for sheet in sheets if sheet["properties"]["title"] == "Inquiries"), None)
    if target is None:
        if len(sheets) != 1 or sheets[0]["properties"]["title"] != "Sheet1":
            raise ValueError("Expected one empty Sheet1 tab; initialization stopped")
        target = sheets[0]
    properties = target["properties"]
    title = properties["title"].replace("'", "''")
    existing = repository.values.get(
        spreadsheetId=repository.sheet_id, range=f"'{title}'",
    ).execute().get("values", [])
    if any(any(str(value).strip() for value in row) for row in existing):
        if properties["title"] == "Inquiries":
            repository.load()  # Existing valid tickets are preserved on reruns.
            print("Existing Inquiries data preserved.")
            return
        raise ValueError("Sheet1 contains data; initialization stopped without overwriting it")
    service.spreadsheets().batchUpdate(
        spreadsheetId=repository.sheet_id,
        body={"requests": [{"updateSheetProperties": {
            "properties": {"sheetId": properties["sheetId"], "title": "Inquiries",
                           "gridProperties": {"frozenRowCount": 1}},
            "fields": "title,gridProperties.frozenRowCount",
        }}]},
    ).execute()
    samples = CsvRepository(ROOT / "data/sample_inquiries.csv").load()
    repository.values.update(
        spreadsheetId=repository.sheet_id, range="Inquiries!A1:L7", valueInputOption="RAW",
        body={"values": [FIELDS, *[[row[field] for field in FIELDS] for row in samples]]},
    ).execute()
    header_range = {"sheetId": properties["sheetId"], "startRowIndex": 0,
                    "endRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": 12}
    service.spreadsheets().batchUpdate(
        spreadsheetId=repository.sheet_id,
        body={"requests": [
            {"repeatCell": {"range": header_range,
                            "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                            "fields": "userEnteredFormat.textFormat.bold"}},
            {"autoResizeDimensions": {"dimensions": {"sheetId": properties["sheetId"],
                                                       "dimension": "COLUMNS", "startIndex": 0, "endIndex": 12}}},
        ]},
    ).execute()
    assert len(repository.load()) == 6
    print("Initialized Inquiries with 12 headers and 6 synthetic NEW tickets.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--initialize", action="store_true")
    parser.add_argument("--retry-ticket", help="Explicitly reset one ERROR ticket before verification")
    args = parser.parse_args()
    repository = SheetsRepository()
    service = build("sheets", "v4", http=repository.values._http, cache_discovery=False)
    if args.initialize:
        initialize(repository, service)
    if args.retry_ticket:
        retry_ticket(repository, args.retry_ticket)
    rows = repository.load()
    print(f"Sheets read verified: {len(rows)} valid ticket rows.")
    pending = [row for row in rows if row["status"] == "NEW"]
    if pending:
        ticket_id = pending[0]["id"]
        result = process_new(repository, analyze_inquiry, limit=1, report=print)
        if result.succeeded != 1:
            raise RuntimeError("Live analysis did not save a draft; inspect ticket error status")
    else:
        ticket_id = next(row["id"] for row in rows if row["status"] in ("DRAFTED", "APPROVED"))
    saved = next(row for row in repository.load() if row["id"] == ticket_id)
    assert saved["status"] in ("DRAFTED", "APPROVED") and saved["draft_reply"]

    class VerifiedTicketRepository:
        def load(self):
            return [row for row in repository.load() if row["id"] == ticket_id]

        def update(self, *args, **kwargs):
            raise AssertionError("A processed ticket must never be rewritten by a repeat run")

    def unexpected_analysis(_message):
        raise AssertionError("A processed ticket must never trigger another AI call")

    repeated = process_new(VerifiedTicketRepository(), unexpected_analysis)
    assert repeated.succeeded == 0 and repeated.failed == 0 and repeated.skipped == 1
    print(f"Saved draft and repeat-run protection verified for {ticket_id}.")
    set_key(str(ROOT / ".env"), "DATA_SOURCE", "sheets")
    print("Local DATA_SOURCE switched to sheets. Restart the dashboard to load updated configuration.")
    print(f"Sheet URL: https://docs.google.com/spreadsheets/d/{repository.sheet_id}/edit")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Verification stopped ({type(exc).__name__}); no secret-bearing provider error is logged.")
        raise SystemExit(1)
