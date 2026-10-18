from unittest.mock import MagicMock

import pytest

from conftest import analysis
from models.ticket import FIELDS
from services.config import ConfigurationError
from services.sheets_service import SheetsRepository
from services.storage import get_repository
from services.ticket_service import approve_ticket, process_new


def test_bad_sheet_headers_rejected_without_writes():
    service = MagicMock()
    values = service.spreadsheets.return_value.values.return_value
    values.get.return_value.execute.return_value = {"values": [["id", "message", "status"]]}
    with pytest.raises(ValueError, match="headers"):
        SheetsRepository(service, "test-sheet").load()
    values.update.assert_not_called()


@pytest.mark.parametrize("defect", ["extra_column", "missing_id", "duplicate_id"])
def test_invalid_sheet_rows_are_rejected(repository, defect):
    rows = [[row[field] for field in FIELDS] for row in repository.load()]
    if defect == "extra_column":
        rows[0].append("unexpected")
    elif defect == "missing_id":
        rows[0][0] = ""
    else:
        rows[1][0] = rows[0][0]
    service = MagicMock()
    values = service.spreadsheets.return_value.values.return_value
    values.get.return_value.execute.return_value = {"values": [FIELDS, *rows]}
    with pytest.raises(ValueError):
        SheetsRepository(service, "test-sheet").load()
    values.update.assert_not_called()


def test_missing_id_update_preserves_repository(repository):
    before = repository.load()
    with pytest.raises(ValueError, match="exactly once"):
        repository.update("MISSING", {"status": "ERROR"}, expected_status="NEW")
    assert repository.load() == before


def test_mixed_status_batch_preserves_processed_tickets(repository):
    process_new(repository, analysis, limit=2)
    approve_ticket(repository, "T001", "Reviewed response.")
    repository.update("T003", {"status": "ERROR", "error_message": "Test failure"}, expected_status="NEW")
    before = repository.load()[:3]
    analyzer = MagicMock(side_effect=analysis)
    result = process_new(repository, analyzer)
    assert result.succeeded == 3 and result.skipped == 3
    assert analyzer.call_count == 3
    assert repository.load()[:3] == before


def test_repository_defaults_to_google_sheets(monkeypatch):
    monkeypatch.delenv("DATA_SOURCE", raising=False)
    factory = MagicMock()
    monkeypatch.setattr("services.sheets_service.SheetsRepository", factory)
    assert get_repository() is factory.return_value


def test_unsupported_source_has_no_local_fallback(monkeypatch):
    monkeypatch.setenv("DATA_SOURCE", "csv")
    with pytest.raises(ConfigurationError, match="Only Google Sheets"):
        get_repository()
