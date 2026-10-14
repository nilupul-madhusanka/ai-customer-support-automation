import csv
import smtplib
from unittest.mock import MagicMock

import pytest

from models.ticket import FIELDS, LEGACY_FIELDS
from services.config import ROOT, ConfigurationError
from services.storage import CsvRepository
from services.ai_service import analyze_offline
from services.ticket_service import approve_ticket, process_new, send_approved_email
from services.email_service import send_reply


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "false")
    repository = CsvRepository(tmp_path / "tickets.csv")
    repository.write(CsvRepository(ROOT / "data/sample_inquiries.csv").load())
    return repository


@pytest.fixture
def configured(monkeypatch):
    for key, value in {"SMTP_HOST": "smtp.gmail.com", "SMTP_PORT": "587", "SMTP_USER": "support@example.com",
                       "SMTP_PASSWORD": "test-password", "SMTP_FROM": "Support Team <support@example.com>"}.items():
        monkeypatch.setenv(key, value)


def test_approval_sends_persisted_edited_reply_once(repo, configured, monkeypatch):
    sender = MagicMock(return_value=True)
    monkeypatch.setattr("services.ticket_service.send_reply", sender)
    process_new(repo, analyze_offline, limit=1)
    sender.assert_not_called()
    approve_ticket(repo, "T001", "  Edited final response.  ")
    sender.assert_called_once_with("amal@example.com", "Amal", "T001", "Edited final response.")
    row = repo.load()[0]
    assert row["email_status"] == "SENT"
    assert row["emailed_at"].endswith("+00:00")
    send_approved_email(repo, "T001")
    with pytest.raises(ValueError):
        approve_ticket(repo, "T001", "Different reply")
    assert sender.call_count == 1


def test_unconfigured_approval_can_be_sent_later(repo, monkeypatch):
    sender = MagicMock(return_value=True)
    monkeypatch.setattr("services.ticket_service.send_reply", sender)
    process_new(repo, analyze_offline, limit=1)
    assert "configure Gmail" in approve_ticket(repo, "T001", "Reviewed reply.")
    assert repo.load()[0]["email_status"] == "NOT_SENT"
    sender.assert_not_called()
    monkeypatch.setattr("services.ticket_service.is_configured", lambda: True)
    send_approved_email(repo, "T001")
    sender.assert_called_once()


def test_demo_never_sends_even_when_configured(repo, configured, monkeypatch):
    sender = MagicMock()
    monkeypatch.setattr("services.ticket_service.send_reply", sender)
    process_new(repo, analyze_offline, limit=1)
    approve_ticket(repo, "T001", "Demo reply.", send_email=False)
    assert repo.load()[0]["email_status"] == "DEMO"
    with pytest.raises(ValueError, match="demo"):
        send_approved_email(repo, "T001")
    sender.assert_not_called()


@pytest.mark.parametrize("failure,status", [(smtplib.SMTPAuthenticationError(535, b'secret'), "FAILED"),
                                          (TimeoutError("secret customer data"), "UNKNOWN")])
def test_failure_preserves_approval_and_requires_safe_retry(repo, configured, monkeypatch, failure, status):
    sender = MagicMock(side_effect=failure)
    monkeypatch.setattr("services.ticket_service.send_reply", sender)
    process_new(repo, analyze_offline, limit=1)
    approve_ticket(repo, "T001", "Reviewed reply.")
    row = repo.load()[0]
    assert row["status"] == "APPROVED" and row["email_status"] == status
    assert not row["emailed_at"] and "secret" not in row["error_message"]
    sender.side_effect = None
    sender.return_value = True
    if status == "UNKNOWN":
        with pytest.raises(ValueError, match="uncertain"):
            send_approved_email(repo, "T001")
    send_approved_email(repo, "T001", confirm_uncertain=True)
    assert repo.load()[0]["email_status"] == "SENT"


def test_no_send_before_approval_or_after_failed_save(repo, configured, monkeypatch):
    sender = MagicMock(return_value=True)
    monkeypatch.setattr("services.ticket_service.send_reply", sender)
    with pytest.raises(ValueError, match="approved"):
        send_approved_email(repo, "T001")
    process_new(repo, analyze_offline, limit=1)
    repo.update = MagicMock(side_effect=OSError("save failed"))
    with pytest.raises(OSError):
        approve_ticket(repo, "T001", "Reviewed reply.")
    sender.assert_not_called()


def test_sent_but_tracking_save_failed_is_not_automatically_resent(repo, configured, monkeypatch):
    sender = MagicMock(return_value=True)
    monkeypatch.setattr("services.ticket_service.send_reply", sender)
    process_new(repo, analyze_offline, limit=1)
    update = repo.update

    def fail_delivery_save(ticket_id, changes, **kwargs):
        if changes.get("email_status") == "SENT":
            raise OSError("save failed")
        update(ticket_id, changes, **kwargs)

    monkeypatch.setattr(repo, "update", fail_delivery_save)
    assert "saving delivery status failed" in approve_ticket(repo, "T001", "Reviewed reply.")
    assert repo.load()[0]["email_status"] == "SENDING"
    with pytest.raises(ValueError, match="uncertain"):
        send_approved_email(repo, "T001")
    sender.assert_called_once()


def test_smtp_uses_tls_envelope_and_unicode(configured, monkeypatch):
    smtp = MagicMock()
    server = smtp.return_value.__enter__.return_value
    server.send_message.return_value = {}
    monkeypatch.setattr("smtplib.SMTP", smtp)
    assert send_reply("customer@example.com", "Nimāli", "TKT-001", "Reviewed café response.")
    server.starttls.assert_called_once()
    assert server.starttls.call_args.kwargs["context"].check_hostname
    server.login.assert_called_once_with("support@example.com", "test-password")
    args = server.send_message.call_args
    assert args.kwargs == {"from_addr": "support@example.com", "to_addrs": ["customer@example.com"]}
    assert "Reviewed café response." in args.args[0].get_content()


@pytest.mark.parametrize("address", ["a@example.com\nBcc: b@example.com", "a@example.com,b@example.com", "bad"])
def test_invalid_recipient_never_connects(configured, address):
    with pytest.raises(ValueError):
        send_reply(address, "Customer", "T001", "Reviewed response.")


def test_legacy_csv_upgrades_on_write(tmp_path):
    path = tmp_path / "legacy.csv"
    sample = CsvRepository(ROOT / "data/sample_inquiries.csv").load()
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=LEGACY_FIELDS)
        writer.writeheader()
        writer.writerows([{key: row[key] for key in LEGACY_FIELDS} for row in sample])
    repo = CsvRepository(path)
    assert repo.load()[0]["email_status"] == ""
    repo.write(repo.load())
    assert path.read_text().splitlines()[0] == ",".join(FIELDS)


def test_legacy_sheet_requires_headers_before_any_update(repo):
    from services.sheets_service import SheetsRepository
    service = MagicMock()
    values = service.spreadsheets.return_value.values.return_value
    values.get.return_value.execute.return_value = {"values": [LEGACY_FIELDS, [repo.load()[0][key] for key in LEGACY_FIELDS]]}
    sheet = SheetsRepository(service, "test-sheet")
    assert sheet.load()[0]["email_status"] == ""
    with pytest.raises(ConfigurationError, match="N1"):
        sheet.update("T001", {"status": "ERROR"}, expected_status="NEW")
    values.update.assert_not_called()


def test_readonly_blocks_email_retry(repo, configured, monkeypatch):
    process_new(repo, analyze_offline, limit=1)
    monkeypatch.setattr("services.ticket_service.is_configured", lambda: False)
    approve_ticket(repo, "T001", "Reviewed reply.")
    monkeypatch.setenv("DEMO_MODE", "true")
    sender = MagicMock(return_value=True)
    monkeypatch.setattr("services.ticket_service.send_reply", sender)
    with pytest.raises(ConfigurationError):
        send_approved_email(repo, "T001")
    sender.assert_not_called()


def test_sheet_missing_customer_email_reports_exact_column():
    from services.sheets_service import SheetsRepository
    service = MagicMock()
    values = service.spreadsheets.return_value.values.return_value
    headers = [field for field in LEGACY_FIELDS if field != "customer_email"] + ["", "email_status", "emailed_at"]
    values.get.return_value.execute.return_value = {"values": [headers]}
    with pytest.raises(ValueError, match="D1 must be 'customer_email'"):
        SheetsRepository(service, "test-sheet").load()
    values.update.assert_not_called()
