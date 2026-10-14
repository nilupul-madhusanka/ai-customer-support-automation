from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from models.ticket import FIELDS, TicketAnalysis
from services.config import ConfigurationError, ROOT
from services.storage import CsvRepository
from services.ticket_service import approve_ticket, process_new, retry_ticket


@pytest.fixture
def repository(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "false")
    repo = CsvRepository(tmp_path / "tickets.csv")
    repo.write(CsvRepository(ROOT / "data/sample_inquiries.csv").load())
    return repo


def analysis(_message):
    return TicketAnalysis(category="General", priority="Low", summary="Customer requests assistance.",
                          draft_reply="Hello, could you please share more details about your request?")


def test_batch_persists_and_second_run_never_calls_analyzer(repository):
    analyzer = MagicMock(side_effect=analysis)
    result = process_new(repository, analyzer)
    assert (result.succeeded, result.failed, analyzer.call_count) == (6, 0, 6)
    assert all(row["status"] == "DRAFTED" for row in repository.load())
    analyzer.reset_mock()
    assert process_new(repository, analyzer).succeeded == 0
    analyzer.assert_not_called()


def test_failure_is_safe_and_explicit_retry_required(repository):
    def fail(_):
        raise RuntimeError("secret-key-private-message")
    result = process_new(repository, fail, limit=1)
    assert result.failed == 1
    row = repository.load()[0]
    assert row["status"] == "ERROR"
    assert "secret" not in row["error_message"]
    retry_ticket(repository, row["id"])
    assert repository.load()[0]["status"] == "NEW"
    assert repository.load()[0]["error_message"] == ""
    with pytest.raises(ValueError):
        retry_ticket(repository, row["id"])


def test_review_saves_edited_reply_and_preserves_original(repository):
    process_new(repository, analysis, limit=1)
    draft = repository.load()[0]["draft_reply"]
    approve_ticket(repository, "T001", "  Reviewed custom response.  ")
    row = repository.load()[0]
    assert row["status"] == "APPROVED"
    assert row["final_reply"] == "Reviewed custom response."
    assert row["draft_reply"] == draft
    assert row["reviewed_at"].endswith("+00:00")
    with pytest.raises(ValueError):
        approve_ticket(repository, "T001", "Another reply")


def test_new_and_blank_reply_cannot_be_approved(repository):
    with pytest.raises(ValueError):
        approve_ticket(repository, "T001", "Reviewed reply")
    process_new(repository, analysis, limit=1)
    with pytest.raises(ValueError):
        approve_ticket(repository, "T001", "   ")
    assert repository.load()[0]["status"] == "DRAFTED"


def test_invalid_ai_payload_is_error(repository):
    process_new(repository, lambda _: {"category": "Unsupported"}, limit=1)
    assert repository.load()[0]["status"] == "ERROR"


def test_duplicate_ids_and_extra_fields_rejected(repository):
    rows = repository.load()
    rows[1]["id"] = rows[0]["id"]
    with pytest.raises(ValueError):
        repository.write(rows)
    with pytest.raises(ValueError):
        repository.update("T001", {"id": "T999"}, expected_status="NEW")


def test_storage_failure_aborts_instead_of_attempting_an_error_write(repository):
    repository.update = MagicMock(side_effect=OSError("disk unavailable"))
    with pytest.raises(OSError):
        process_new(repository, analysis)
    assert repository.update.call_count == 1


def test_readonly_guards_every_business_mutation(repository, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    for action in (lambda: process_new(repository, analysis),
                   lambda: approve_ticket(repository, "T001", "Response"),
                   lambda: retry_ticket(repository, "T001")):
        with pytest.raises(ConfigurationError):
            action()
    assert all(row["status"] == "NEW" for row in repository.load())


def test_analysis_rejects_extra_keys_and_whitespace():
    payload = analysis("").model_dump()
    with pytest.raises(ValidationError):
        TicketAnalysis.model_validate({**payload, "unexpected": "value"})
    with pytest.raises(ValidationError):
        TicketAnalysis.model_validate({**payload, "summary": "     "})


def test_sheets_pads_empty_cells_and_updates_actual_row_by_id(repository):
    from services.sheets_service import SheetsRepository
    service = MagicMock()
    values = service.spreadsheets.return_value.values.return_value
    rows = repository.load()
    cells = [[row[field] for field in FIELDS[:6]] for row in rows]
    values.get.return_value.execute.return_value = {"values": [FIELDS, cells[1], [], cells[0]]}
    sheet = SheetsRepository(service, "test-sheet")
    assert sheet.load()[1]["draft_reply"] == ""
    sheet.update("T001", {**analysis("").model_dump(), "status": "DRAFTED"}, expected_status="NEW")
    arguments = values.update.call_args.kwargs
    assert arguments["range"] == "Inquiries!A4:O4"
    assert arguments["valueInputOption"] == "RAW"
    assert arguments["body"]["values"][0][0] == "T001"
