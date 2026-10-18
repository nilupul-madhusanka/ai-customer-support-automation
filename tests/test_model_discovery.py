from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest
from google.genai.errors import ClientError, ServerError

from conftest import analysis
from services.ai_service import AnalysisFailure, analyze_inquiry, model_policy
from services.model_discovery import clear_model_cache, discover_models, eligible_model
from services.ticket_service import process_new


def model(name, actions=None):
    return SimpleNamespace(name=name, supported_actions=actions if actions is not None else ["generateContent"])


def response():
    return MagicMock(text=analysis("").model_dump_json())


def error(code):
    cls = ServerError if code >= 500 else ClientError
    return cls(code, {"error": {"code": code, "message": "SECRET_PROVIDER_TEXT"}})


@pytest.fixture
def automatic(monkeypatch):
    clear_model_cache()
    monkeypatch.setenv("GEMINI_AUTO_DISCOVER", "true")
    monkeypatch.setenv("GEMINI_API_KEY", "test-discovery-key")
    monkeypatch.setenv("GEMINI_MODEL", "preferred")
    monkeypatch.setenv("GEMINI_TIME_BUDGET_SECONDS", "90")
    with patch("google.genai.Client") as factory:
        client = factory.return_value.__enter__.return_value
        client.models.list.return_value = [model("models/gemini-9.0-flash"), model("models/gemini-8.0-pro")]
        yield client
    clear_model_cache()


def test_missing_primary_automatically_discovers_and_drafts(automatic, repository):
    automatic.models.generate_content.side_effect = [error(404), response()]
    result = process_new(repository, analyze_inquiry, limit=1)
    assert result.succeeded == 1
    assert [call.kwargs["model"] for call in automatic.models.generate_content.call_args_list] == ["preferred", "gemini-9.0-flash"]
    automatic.models.list.assert_called_once()


def test_gateway_timeout_automatically_uses_discovered_fallback(automatic):
    automatic.models.generate_content.side_effect = [error(504), response()]
    updates = []
    result = analyze_inquiry("Please help with my account.", report=updates.append)
    assert result.model == "gemini-9.0-flash"
    assert [item["outcome"] for item in result.attempts] == ["HTTP_504", "SUCCESS"]
    assert any("preferred" in item for item in updates)
    assert any("gemini-9.0-flash" in item for item in updates)


def test_request_timeout_leaves_room_for_next_model(automatic):
    automatic.models.generate_content.side_effect = [httpx.ReadTimeout("SECRET"), response()]
    result = analyze_inquiry("Please help.")
    assert result.model == "gemini-9.0-flash"
    assert result.attempts[0]["outcome"] == "PROVIDER_TIMEOUT"
    assert automatic.models.generate_content.call_args_list[0].kwargs["config"].http_options.timeout <= 30000


def test_no_primary_is_required_when_discovery_is_enabled(automatic, monkeypatch):
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    assert model_policy().models == ()
    automatic.models.generate_content.return_value = response()
    assert analyze_inquiry("Please help.").model == "gemini-9.0-flash"


def test_discovery_prefers_general_flash_and_ignores_specialized_models(automatic, monkeypatch):
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    automatic.models.list.return_value = [
        model("models/gemini-9.0-pro"), model("models/gemini-9.0-flash-preview"),
        model("models/gemini-8.0-flash"), model("models/gemini-9.0-flash"),
        model("models/gemini-9.0-flash-image"), model("models/gemini-live-9.0-flash"),
        model("models/gemini-9.0-flash-tts"), model("models/embedding-001"),
        model("models/gemini-9.0-flash-native-audio"), model("models/imagen-9.0"),
        model("models/gemini-9.0-flash-no-generation", ["countTokens"]),
    ]
    automatic.models.generate_content.return_value = response()
    assert analyze_inquiry("Please help.").model == "gemini-9.0-flash"
    names = discover_models(automatic, "test-discovery-key", timeout_ms=1000)
    assert names == ("gemini-9.0-flash", "gemini-8.0-flash", "gemini-9.0-pro", "gemini-9.0-flash-preview")


def test_catalog_cached_per_key_and_refreshed_after_expiry(automatic, monkeypatch):
    clock = MagicMock(return_value=0.0)
    monkeypatch.setattr("services.model_discovery.time.monotonic", clock)
    first = discover_models(automatic, "key-one", timeout_ms=1000)
    assert discover_models(automatic, "key-one", timeout_ms=1000) == first
    automatic.models.list.assert_called_once()
    discover_models(automatic, "key-two", timeout_ms=1000)
    assert automatic.models.list.call_count == 2
    clock.return_value = 301.0
    discover_models(automatic, "key-one", timeout_ms=1000)
    assert automatic.models.list.call_count == 3


def test_catalog_failure_can_use_explicit_primary(automatic):
    automatic.models.list.side_effect = error(503)
    automatic.models.generate_content.return_value = response()
    assert analyze_inquiry("Please help.").model == "preferred"


def test_catalog_failure_without_primary_is_safe(automatic, monkeypatch):
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    automatic.models.list.side_effect = error(503)
    with pytest.raises(AnalysisFailure) as caught:
        analyze_inquiry("Please help.")
    assert caught.value.code == "MODEL_DISCOVERY_FAILED"
    assert "SECRET" not in str(caught.value)
    automatic.models.generate_content.assert_not_called()


@pytest.mark.parametrize("code,reason", [(401, "PROVIDER_AUTH"), (403, "PROVIDER_AUTH"), (429, "PROVIDER_RATE_LIMIT")])
def test_discovery_auth_and_rate_limit_never_trigger_generation(automatic, code, reason):
    automatic.models.list.side_effect = error(code)
    with pytest.raises(AnalysisFailure) as caught:
        analyze_inquiry("Please help.")
    assert caught.value.code == reason and caught.value.stop_batch
    automatic.models.generate_content.assert_not_called()


def test_listed_models_do_not_evade_generation_rate_limit(automatic):
    automatic.models.generate_content.side_effect = error(429)
    with pytest.raises(AnalysisFailure) as caught:
        analyze_inquiry("Please help.")
    assert caught.value.code == "PROVIDER_RATE_LIMIT"
    automatic.models.generate_content.assert_called_once()


@pytest.mark.parametrize("invalid", ["", "SECRET_INVALID_JSON"])
def test_discovered_fallback_can_recover_invalid_model_output(automatic, invalid):
    automatic.models.generate_content.side_effect = [MagicMock(text=invalid), response()]
    result = analyze_inquiry("Please help.")
    assert result.model == "gemini-9.0-flash"
    assert len(result.attempts) == 2


def test_incompatible_structured_output_candidate_is_skipped(automatic):
    automatic.models.generate_content.side_effect = [error(400), response()]
    assert analyze_inquiry("Please help.").model == "gemini-9.0-flash"


def test_discovered_candidates_still_obey_attempt_limit(automatic, monkeypatch):
    monkeypatch.setenv("GEMINI_MAX_ATTEMPTS", "2")
    automatic.models.generate_content.side_effect = error(503)
    with pytest.raises(AnalysisFailure) as caught:
        analyze_inquiry("Please help.")
    assert len(caught.value.attempts) == automatic.models.generate_content.call_count == 2


def test_no_suitable_catalog_models_is_actionable(automatic, monkeypatch):
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    automatic.models.list.return_value = [model("models/gemini-9.0-flash-image")]
    with pytest.raises(AnalysisFailure) as caught:
        analyze_inquiry("Please help.")
    assert caught.value.code == "NO_SUITABLE_MODELS"


def test_metadata_action_names_and_invalid_names_are_handled():
    assert eligible_model(model("models/gemini-9.0-flash", ["generate_content"])) == "gemini-9.0-flash"
    assert eligible_model(model("models/gemini-SECRET\n-flash")) is None
    assert eligible_model(model(None)) is None
