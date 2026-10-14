import pytest


@pytest.fixture(autouse=True)
def isolate_email(monkeypatch):
    """Tests must never use SMTP credentials from the local .env."""
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)

    def blocked(*args, **kwargs):
        raise AssertionError("Tests must mock SMTP; external email is disabled")

    monkeypatch.setattr("smtplib.SMTP", blocked)
