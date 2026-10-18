from streamlit.testing.v1 import AppTest

from services.config import ROOT
from conftest import analysis
from unittest.mock import MagicMock


def test_dashboard_process_edit_approve_and_filter(repository, monkeypatch):
    sender = MagicMock(return_value=True)
    monkeypatch.setattr("services.ticket_service.send_reply", sender)
    monkeypatch.setattr("services.ticket_service.is_configured", lambda: True)
    monkeypatch.setenv("READ_ONLY", "false")
    monkeypatch.setattr("services.ai_service.require_gemini_config", lambda: None)
    monkeypatch.setattr("services.ai_service.analyze_inquiry", analysis)
    monkeypatch.setattr("services.storage.get_repository", lambda **kwargs: repository)
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    assert not app.exception
    assert not app.toggle
    app.button[0].click().run()
    assert not app.exception
    assert all(row["status"] == "DRAFTED" for row in repository.load())
    app.text_area[0].set_value("A response edited by the reviewer.")
    next(button for button in app.button if button.label == "Approve and send email").click().run()
    assert not app.exception
    assert repository.load()[0]["final_reply"] == "A response edited by the reviewer."
    assert repository.load()[0]["email_status"] == "SENT"
    sender.assert_called_once()
    app.selectbox[0].select("APPROVED").run()
    assert not app.exception
    assert app.success[0].value == "Reviewed and approved"


def test_dashboard_live_approval_emails_reviewed_reply(repository, monkeypatch):
    from services.ticket_service import process_new
    monkeypatch.setenv("READ_ONLY", "false")
    monkeypatch.setattr("services.ai_service.require_gemini_config", lambda: None)
    monkeypatch.setattr("services.ai_service.analyze_inquiry", analysis)
    process_new(repository, analysis, limit=1)
    monkeypatch.setattr("services.storage.get_repository", lambda **kwargs: repository)
    monkeypatch.setattr("services.ticket_service.is_configured", lambda: True)
    sender = MagicMock(return_value=True)
    monkeypatch.setattr("services.ticket_service.send_reply", sender)
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    app.text_area[0].set_value("Human reviewed live response.")
    next(button for button in app.button if button.label == "Approve and send email").click().run()
    assert not app.exception
    sender.assert_called_once_with("amal@example.com", "Amal", "T001", "Human reviewed live response.")
    assert repository.load()[0]["email_status"] == "SENT"
