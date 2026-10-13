import csv

import pytest

from models.ticket import FIELDS
from services.config import ROOT
from services.storage import CsvRepository
from services.ticket_service import approve_ticket, process_new
from services.ai_service import analyze_offline


def test_bad_headers_are_rejected_without_changing_file(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("id,message,status\nT001,hello,NEW\n", encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="headers"):
        CsvRepository(path).load()
    assert path.read_bytes() == before


@pytest.mark.parametrize("extra", [False, True])
def test_malformed_csv_rows_are_rejected(tmp_path, extra):
    path = tmp_path / "malformed.csv"
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(FIELDS)
        writer.writerow(["T001", "2026-10-13", "Synthetic", "Hello", "NEW"] +
                        ([""] * 7 + ["unexpected"] if extra else []))
    with pytest.raises(ValueError):
        CsvRepository(path).load()


def test_missing_id_update_preserves_repository(tmp_path):
    repo = CsvRepository(tmp_path / "tickets.csv")
    repo.write(CsvRepository(ROOT / "data/sample_inquiries.csv").load())
    before = repo.path.read_bytes()
    with pytest.raises(ValueError, match="exactly once"):
        repo.update("MISSING", {"status": "ERROR"}, expected_status="NEW")
    assert repo.path.read_bytes() == before


def test_mixed_status_batch_preserves_approved_drafted_and_error_tickets(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "false")
    repo = CsvRepository(tmp_path / "mixed.csv")
    repo.write(CsvRepository(ROOT / "data/sample_inquiries.csv").load())
    process_new(repo, analyze_offline, limit=2)
    approve_ticket(repo, "T001", "Reviewed synthetic reply.")
    repo.update("T003", {"status": "ERROR", "error_message": "Synthetic test failure"}, expected_status="NEW")
    before = repo.load()[:3]
    analyzed = []

    def analyzer(message):
        analyzed.append(message)
        return analyze_offline(message)

    result = process_new(repo, analyzer)
    assert result.succeeded == 3 and result.skipped == 3
    assert len(analyzed) == 3
    assert repo.load()[:3] == before
