"""Regression coverage for the October review and the refreshed core audit."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import smtplib
import subprocess
import sys
import threading
from unittest.mock import MagicMock, patch

import pytest
from google.genai.errors import ClientError, ServerError
from streamlit.testing.v1 import AppTest

from conftest import analysis
from models.ticket import validate_rows
from services.ai_service import AnalysisFailure, AnalysisResult, analyze_inquiry, model_policy
from services.config import ROOT, ConfigurationError, read_only
from services.errors import BusyError, SourceValidationError, public_error
from services.ticket_service import approve_ticket, process_new, retry_ticket, send_approved_email
from services.writer_lock import writer_lock


@pytest.fixture
def gemini(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_MODEL", "primary")
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "missing,available")
    with patch("google.genai.Client") as factory:
        yield factory.return_value.__enter__.return_value


def response():
    return MagicMock(text=analysis("").model_dump_json())


def api_error(code, *, retry_after=False):
    cls = ServerError if code >= 500 else ClientError
    return cls(code, {"error": {"message": "SECRET_PROVIDER_PAYLOAD", "code": code}},
               response=MagicMock(headers={"retry-after": "60"} if retry_after else {}))


def test_fallback_skips_missing_candidate_and_records_actual_model(gemini, repository):
    gemini.models.generate_content.side_effect = [api_error(503), api_error(404), response()]
    result = process_new(repository, analyze_inquiry, limit=1)
    assert result.succeeded == 1
    calls = gemini.models.generate_content.call_args_list
    assert [call.kwargs["model"] for call in calls] == ["primary", "missing", "available"]
    audit = json.loads(Path(os.environ["ANALYSIS_AUDIT_PATH"]).read_text())
    assert audit["model"] == "available" and audit["ticket_id"] == "T001"
    assert [item["outcome"] for item in audit["attempts"]] == ["HTTP_503", "HTTP_404", "SUCCESS"]
    assert "SECRET_PROVIDER_PAYLOAD" not in json.dumps(audit)
    assert repository.load()[0]["message"] not in json.dumps(audit)


def test_busy_primary_can_use_allowed_fallback(gemini):
    gemini.models.generate_content.side_effect = [api_error(503), response()]
    result = analyze_inquiry("Please help")
    assert result.model == "missing" and len(result.attempts) == 2


@pytest.mark.parametrize("code,reason", [(401, "PROVIDER_AUTH"), (403, "PROVIDER_AUTH"),
                                         (400, "PROVIDER_CONFIG"), (404, "PROVIDER_CONFIG"),
                                         (429, "PROVIDER_RATE_LIMIT")])
def test_global_provider_failure_stops_batch_and_preserves_new_tickets(gemini, repository, code, reason):
    gemini.models.generate_content.side_effect = api_error(code)
    result = process_new(repository, analyze_inquiry)
    assert reason in result.stopped_reason
    assert result.failed == result.succeeded == 0 and result.skipped == 6
    assert all(row["status"] == "NEW" for row in repository.load())
    gemini.models.generate_content.assert_called_once()
    assert "SECRET_PROVIDER_PAYLOAD" not in Path(os.environ["ANALYSIS_AUDIT_PATH"]).read_text()


def test_retry_after_stops_without_immediate_fallback(gemini):
    gemini.models.generate_content.side_effect = api_error(503, retry_after=True)
    with pytest.raises(AnalysisFailure, match="requested a wait"):
        analyze_inquiry("Please help")
    gemini.models.generate_content.assert_called_once()


@pytest.mark.parametrize("text,reason", [("", "OUTPUT_EMPTY"), ("SECRET_NOT_JSON", "OUTPUT_INVALID"),
                                         ('{"summary":"SECRET_WRONG_SCHEMA"}', "OUTPUT_INVALID")])
def test_bad_output_is_safe_and_does_not_trigger_fallback(gemini, text, reason):
    gemini.models.generate_content.return_value = MagicMock(text=text)
    with pytest.raises(AnalysisFailure) as caught:
        analyze_inquiry("Please help")
    assert caught.value.code == reason
    assert "SECRET" not in str(caught.value)
    gemini.models.generate_content.assert_called_once()


def test_attempt_budget_caps_fallbacks(gemini, monkeypatch):
    monkeypatch.setenv("GEMINI_MAX_ATTEMPTS", "2")
    gemini.models.generate_content.side_effect = api_error(503)
    with pytest.raises(AnalysisFailure, match="budget") as caught:
        analyze_inquiry("Please help")
    assert len(caught.value.attempts) == gemini.models.generate_content.call_count == 2


def test_time_budget_prevents_starting_later_attempts(gemini, monkeypatch):
    clock = MagicMock(side_effect=[0.0, 10.0, 31.0])
    monkeypatch.setattr("services.ai_service.time.monotonic", clock)
    gemini.models.generate_content.side_effect = api_error(503)
    with pytest.raises(AnalysisFailure, match="budget"):
        analyze_inquiry("Please help")
    gemini.models.generate_content.assert_called_once()
    assert gemini.models.generate_content.call_args.kwargs["config"].http_options.timeout == 6666


def test_policy_deduplicates_and_validates_budget(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "primary")
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "primary, allowed,allowed")
    assert model_policy().models == ("primary", "allowed")
    monkeypatch.setenv("GEMINI_MAX_ATTEMPTS", "SECRET_BAD_NUMBER")
    with pytest.raises(ConfigurationError) as caught:
        model_policy()
    assert "SECRET_BAD_NUMBER" not in str(caught.value)


def test_batch_storage_failure_reports_already_committed_work(repository, monkeypatch):
    update = repository.update

    def fail_second(ticket_id, *args, **kwargs):
        if ticket_id == "T002":
            raise OSError("SECRET_STORAGE")
        return update(ticket_id, *args, **kwargs)

    monkeypatch.setattr(repository, "update", fail_second)
    result = process_new(repository, analysis)
    assert result.succeeded == 1 and result.skipped == 5
    assert "STORAGE_WRITE_FAILED" in result.stopped_reason
    assert "SECRET_STORAGE" not in result.stopped_reason
    assert [row["status"] for row in repository.load()] == ["DRAFTED", *["NEW"] * 5]


def test_audit_failure_stops_before_saving_draft(repository, monkeypatch):
    monkeypatch.setattr("services.ticket_service.record_analysis", MagicMock(side_effect=OSError("full")))
    result = process_new(repository, analysis)
    assert result.stopped_reason and result.skipped == 6
    assert repository.load()[0]["status"] == "NEW"


def test_approval_saved_when_send_intent_write_fails(repository, monkeypatch):
    process_new(repository, analysis, limit=1)
    update = repository.update

    def fail_intent(ticket_id, changes, **kwargs):
        if changes.get("email_status") == "SENDING":
            raise OSError("SECRET_STORAGE")
        return update(ticket_id, changes, **kwargs)

    monkeypatch.setattr(repository, "update", fail_intent)
    monkeypatch.setattr("services.ticket_service.is_configured", lambda: True)
    sender = MagicMock()
    monkeypatch.setattr("services.ticket_service.send_reply", sender)
    outcome = approve_ticket(repository, "T001", "Reviewed reply.")
    assert outcome.approval_saved and not outcome.delivery.attempted
    assert not outcome.delivery.tracking_saved
    assert "Approval saved" in outcome.message and "not attempted" in outcome.message
    assert "SECRET_STORAGE" not in outcome.message
    assert repository.load()[0]["status"] == "APPROVED"
    sender.assert_not_called()


def test_approval_write_commits_then_loses_response_without_sending(repository, monkeypatch):
    process_new(repository, analysis, limit=1)
    update = repository.update

    def commit_then_fail(*args, **kwargs):
        update(*args, **kwargs)
        raise TimeoutError("SECRET_WRITE_RESPONSE")

    monkeypatch.setattr(repository, "update", commit_then_fail)
    sender = MagicMock()
    monkeypatch.setattr("services.ticket_service.send_reply", sender)
    outcome = approve_ticket(repository, "T001", "Reviewed reply.")
    assert outcome.approval_saved and not outcome.delivery.attempted
    assert repository.load()[0]["status"] == "APPROVED"
    assert "confirmed after a source error" in outcome.message
    sender.assert_not_called()


def test_approval_write_and_readback_fail_reports_unknown_without_sending(repository, monkeypatch):
    process_new(repository, analysis, limit=1)
    monkeypatch.setattr(repository, "update", MagicMock(side_effect=TimeoutError("SECRET_WRITE")))
    monkeypatch.setattr(repository, "load", MagicMock(side_effect=OSError("SECRET_READ")))
    sender = MagicMock()
    monkeypatch.setattr("services.ticket_service.send_reply", sender)
    outcome = approve_ticket(repository, "T001", "Reviewed reply.")
    assert outcome.approval_saved is None and not outcome.delivery.attempted
    assert "could not be confirmed" in outcome.message and "SECRET" not in outcome.message
    sender.assert_not_called()


def test_failed_delivery_tracking_save_after_acceptance_is_structured(repository, monkeypatch):
    process_new(repository, analysis, limit=1)
    update = repository.update

    def fail_sent(ticket_id, changes, **kwargs):
        if changes.get("email_status") == "SENT":
            raise OSError("SECRET")
        return update(ticket_id, changes, **kwargs)

    monkeypatch.setattr(repository, "update", fail_sent)
    monkeypatch.setattr("services.ticket_service.is_configured", lambda: True)
    monkeypatch.setattr("services.ticket_service.send_reply", MagicMock(return_value=True))
    outcome = approve_ticket(repository, "T001", "Reviewed reply.")
    assert outcome.approval_saved and outcome.delivery.attempted and outcome.delivery.smtp_accepted
    assert not outcome.delivery.tracking_saved and outcome.delivery.status == "SENDING"
    assert repository.load()[0]["email_status"] == "SENDING"


def test_sender_reports_unconfigured_after_preflight_persists_reason(repository, monkeypatch):
    process_new(repository, analysis, limit=1)
    monkeypatch.setattr("services.ticket_service.is_configured", lambda: True)
    monkeypatch.setattr("services.ticket_service.send_reply", MagicMock(return_value=False))
    outcome = approve_ticket(repository, "T001", "Reviewed reply.")
    assert outcome.approval_saved and not outcome.delivery.smtp_accepted
    assert repository.load()[0]["email_status"] == "NOT_SENT"
    assert "configure Gmail" in repository.load()[0]["error_message"]


@pytest.mark.parametrize("failure,status", [(TimeoutError("SECRET"), "UNKNOWN"),
                                           (smtplib.SMTPAuthenticationError(535, b'SECRET'), "FAILED")])
def test_tracking_failure_after_smtp_failure_preserves_uncertainty(repository, monkeypatch, failure, status):
    process_new(repository, analysis, limit=1)
    update = repository.update

    def fail_tracking(ticket_id, changes, **kwargs):
        if changes.get("email_status") == status:
            raise OSError("SECRET_STORAGE")
        return update(ticket_id, changes, **kwargs)

    monkeypatch.setattr(repository, "update", fail_tracking)
    monkeypatch.setattr("services.ticket_service.is_configured", lambda: True)
    monkeypatch.setattr("services.ticket_service.send_reply", MagicMock(side_effect=failure))
    outcome = approve_ticket(repository, "T001", "Reviewed reply.")
    assert outcome.approval_saved and outcome.delivery.attempted
    assert not outcome.delivery.tracking_saved
    assert outcome.delivery.status == repository.load()[0]["email_status"] == "SENDING"
    assert "SECRET" not in outcome.message and "check Gmail Sent" in outcome.message
    with pytest.raises(ValueError, match="uncertain"):
        send_approved_email(repository, "T001")


def test_missing_smtp_reason_is_persisted(repository):
    process_new(repository, analysis, limit=1)
    approve_ticket(repository, "T001", "Reviewed reply.")
    row = repository.load()[0]
    assert row["status"] == "APPROVED" and row["email_status"] == "NOT_SENT"
    assert "configure Gmail" in row["error_message"]


def test_missing_recipient_reason_survives_reload(repository, monkeypatch):
    process_new(repository, analysis, limit=1)
    approve_ticket(repository, "T001", "Reviewed reply.")
    load = repository.load
    monkeypatch.setattr(repository, "load", lambda: [{**row, "customer_email": ""} for row in load()])
    outcome = send_approved_email(repository, "T001")
    assert not outcome.attempted and "no customer email" in outcome.message
    assert "no customer email" in repository.load()[0]["error_message"]


def test_simultaneous_sends_make_only_one_smtp_call(repository, monkeypatch):
    process_new(repository, analysis, limit=1)
    approve_ticket(repository, "T001", "Reviewed reply.")
    monkeypatch.setattr("services.ticket_service.is_configured", lambda: True)
    entered, finish = threading.Event(), threading.Event()

    def send(*args):
        entered.set()
        assert finish.wait(5)
        return True

    sender = MagicMock(side_effect=send)
    monkeypatch.setattr("services.ticket_service.send_reply", sender)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(send_approved_email, repository, "T001")
        try:
            assert entered.wait(5)
            with pytest.raises(BusyError):
                send_approved_email(repository, "T001")
        finally:
            finish.set()
        assert first.result(timeout=5).smtp_accepted
    sender.assert_called_once()


def test_simultaneous_analysis_makes_only_one_claim(repository):
    entered, finish = threading.Event(), threading.Event()

    def analyze(message):
        entered.set()
        assert finish.wait(5)
        return analysis(message)

    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(process_new, repository, analyze, limit=1)
        try:
            assert entered.wait(5)
            for action in (lambda: process_new(repository, analysis),
                           lambda: approve_ticket(repository, "T001", "Reviewed reply."),
                           lambda: retry_ticket(repository, "T001")):
                with pytest.raises(BusyError):
                    action()
        finally:
            finish.set()
        assert first.result(timeout=5).succeeded == 1


def test_writer_lock_is_enforced_across_processes_and_released(repository):
    code = """
from types import SimpleNamespace
from services.writer_lock import writer_lock
from services.errors import BusyError
try:
    with writer_lock(SimpleNamespace(sheet_id='test-sheet')):
        pass
except BusyError:
    raise SystemExit(7)
"""
    with writer_lock(repository):
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, timeout=10, capture_output=True)
        assert result.returncode == 7, result.stderr.decode(errors="replace")
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, timeout=10, capture_output=True)
    assert result.returncode == 0, result.stderr.decode(errors="replace")


def test_stale_email_state_is_rejected_without_overwrite(repository):
    process_new(repository, analysis, limit=1)
    approve_ticket(repository, "T001", "Reviewed reply.")
    repository.update("T001", {"email_status": "SENDING"}, expected_status="APPROVED", expected_email_status="NOT_SENT")
    with pytest.raises(ValueError, match="Email status changed"):
        repository.update("T001", {"email_status": "SENT", "emailed_at": datetime.now(timezone.utc).isoformat()},
                          expected_status="APPROVED", expected_email_status="NOT_SENT")
    assert repository.load()[0]["email_status"] == "SENDING"


@pytest.mark.parametrize("changes", [{"final_reply": "x" * 1201}, {"reviewed_at": "SECRET_BAD_DATE"},
                                     {"reviewed_at": "2026-10-18T12:00:00"},
                                     {"emailed_at": "SECRET_BAD_DATE", "email_status": "SENT"},
                                     {"emailed_at": "2026-10-18T12:00:00Z", "email_status": "NOT_SENT"},
                                     {"category": "SECRET_BAD_CATEGORY"}])
def test_stored_approval_contract_rejects_invalid_data_safely(repository, changes):
    process_new(repository, analysis, limit=1)
    approve_ticket(repository, "T001", "Reviewed reply.")
    row = {**repository.load()[0], **changes}
    with pytest.raises(SourceValidationError) as caught:
        validate_rows([row])
    assert "SECRET" not in str(caught.value) and "Inquiry record 1" in str(caught.value)


def test_nonapproved_delivery_fields_are_rejected(repository):
    row = {**repository.load()[0], "email_status": "FAILED"}
    with pytest.raises(SourceValidationError):
        validate_rows([row])


def test_invalid_readonly_configuration_fails_closed(monkeypatch):
    monkeypatch.setenv("READ_ONLY", "tru")
    with pytest.raises(ConfigurationError):
        read_only()


def test_dashboard_does_not_render_uncontrolled_validation_text(monkeypatch):
    monkeypatch.setenv("READ_ONLY", "false")
    monkeypatch.setattr("services.storage.get_repository", MagicMock(side_effect=ValueError("SECRET_SOURCE_VALUE")))
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    assert not app.exception and app.error
    assert all("SECRET_SOURCE_VALUE" not in item.value for item in app.error)
    assert "SECRET" not in public_error(ValueError("SECRET"))


def test_dashboard_preserves_approval_and_warns_when_intent_save_fails(repository, monkeypatch):
    process_new(repository, analysis, limit=1)
    update = repository.update

    def fail_intent(ticket_id, changes, **kwargs):
        if changes.get("email_status") == "SENDING":
            raise OSError("SECRET")
        return update(ticket_id, changes, **kwargs)

    monkeypatch.setattr(repository, "update", fail_intent)
    monkeypatch.setattr("services.storage.get_repository", lambda: repository)
    monkeypatch.setattr("services.ticket_service.is_configured", lambda: True)
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    next(button for button in app.button if button.label == "Approve and send email").click().run()
    assert not app.exception
    assert repository.load()[0]["status"] == "APPROVED"
    assert any("Approval saved" in item.value and "not attempted" in item.value for item in app.warning)


def test_dashboard_email_preview_uses_edited_message_and_delivery_filter(repository, monkeypatch):
    process_new(repository, analysis, limit=1)
    monkeypatch.setenv("SMTP_USER", "support@example.com")
    monkeypatch.setenv("SMTP_FROM", "Support Team <support@example.com>")
    monkeypatch.setattr("services.storage.get_repository", lambda: repository)
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    app.text_area[0].set_value("Edited response for the customer.").run()
    assert not app.exception
    assert any("Edited response for the customer." in item.value and "Reference: T001" in item.value for item in app.text)
    assert any("To: amal@example.com" in item.value and "Subject:" in item.value for item in app.text)
    next(button for button in app.button if button.label == "Approve reply").click().run()
    app.selectbox[3].select("Unsent approved").run()
    assert not app.exception
    assert len(app.dataframe[0].value) == 1
    next(button for button in app.button if button.label == "Refresh tickets").click().run()
    assert any("configure Gmail" in item.value for item in app.warning)
