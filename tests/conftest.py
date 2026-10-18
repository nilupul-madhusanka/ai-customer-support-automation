import pytest
from copy import deepcopy
from unittest.mock import MagicMock

from models.ticket import FIELDS, TicketAnalysis
from services.sheets_service import SheetsRepository


def analysis(_message, **kwargs):
    return TicketAnalysis(category="General", priority="Low", summary="Customer requests assistance.",
                          draft_reply="Hello, could you please share more details about your request?")


@pytest.fixture
def repository(monkeypatch):
    """Exercise the real Sheets adapter against a mocked Google API."""
    monkeypatch.setenv("READ_ONLY", "false")
    service = MagicMock()
    values = service.spreadsheets.return_value.values.return_value
    cells = [FIELDS.copy()]
    for index in range(1, 7):
        row = dict.fromkeys(FIELDS, "")
        row.update(id=f"T{index:03}", received_at="2026-10-13", customer_name="Amal",
                   customer_email="amal@example.com", message=f"Please help with request {index}.", status="NEW")
        cells.append([row[field] for field in FIELDS])
    values.get.return_value.execute.side_effect = lambda: {"values": deepcopy(cells)}

    def update(**kwargs):
        number = int(kwargs["range"].split("!A")[1].split(":")[0])
        cells[number - 1] = deepcopy(kwargs["body"]["values"][0])
        return MagicMock()

    values.update.side_effect = update
    return SheetsRepository(service, "test-sheet")


@pytest.fixture
def repo(repository):
    return repository


@pytest.fixture(autouse=True)
def isolate_email(monkeypatch, tmp_path):
    """Tests must never use SMTP credentials from the local .env."""
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    monkeypatch.setenv("ANALYSIS_AUDIT_PATH", str(tmp_path / "analysis_attempts.jsonl"))
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "")
    monkeypatch.setenv("GEMINI_AUTO_DISCOVER", "false")
    monkeypatch.setenv("GEMINI_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("GEMINI_TIME_BUDGET_SECONDS", "30")

    def blocked(*args, **kwargs):
        raise AssertionError("Tests must explicitly mock external clients; live AI, Sheets, and SMTP are disabled")

    monkeypatch.setattr("smtplib.SMTP", blocked)
    monkeypatch.setattr("google.genai.Client", blocked)
    monkeypatch.setattr("googleapiclient.discovery.build", blocked)
