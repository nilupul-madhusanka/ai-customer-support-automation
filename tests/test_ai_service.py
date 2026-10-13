from unittest.mock import MagicMock, patch

import pytest

from services.ai_service import analyze_inquiry, require_gemini_config, validate_message
from services.config import ConfigurationError


def test_missing_key_is_preflight_error(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ConfigurationError):
        require_gemini_config()


@pytest.mark.parametrize("message", ["", "   ", "x" * 6001])
def test_input_limits(message):
    with pytest.raises(ValueError):
        validate_message(message)


def test_sdk_request_and_response_validation_without_network(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-test-key")
    monkeypatch.setenv("GEMINI_MODEL", "test-model")
    with patch("google.genai.Client") as factory:
        client = factory.return_value.__enter__.return_value
        client.models.generate_content.return_value = MagicMock(text='{"category":"Billing","priority":"Low","summary":"Customer needs an invoice.","draft_reply":"Hello, please confirm which billing period you need."}')
        result = analyze_inquiry("I need an invoice")
        assert result.category == "Billing"
        assert client.models.generate_content.call_args.kwargs["model"] == "test-model"
        assert factory.call_args.kwargs["http_options"].timeout == 30000
        factory.return_value.__exit__.assert_called_once()
