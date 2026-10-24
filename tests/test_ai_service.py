"""The shared pipeline applies policy without depending on the Gemini SDK."""

import asyncio
import logging
from dataclasses import FrozenInstanceError
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import SecretStr

from app.config.ai import AI_MAX_RESPONSE_LENGTH
from app.config.ai_language import ResponseLanguageSettings
from app.config.settings import Settings
from app.runtime_state import RuntimeState
from app.services.ai_provider import (
    AIGenerationRequest, AIProviderCapabilities, AIProviderResponse, AIProviderSettings,
)
from app.services.ai_service import SharedAIService
from app.services.contracts import AIReply
from app.services.filter_manager import FilterEvaluation, FilterManager
from app.services.gemini_ai_service import GeminiProvider


class SyntheticProvider:
    name = "Synthetic provider"
    capabilities = AIProviderCapabilities(search=False)
    is_available = True

    def __init__(self):
        self.options = AIProviderSettings("synthetic-primary", "synthetic-fallback")
        self.generate = AsyncMock(return_value=AIProviderResponse("A friendly answer."))
        self.discover_models = AsyncMock(return_value=["synthetic-primary"])
        self.aclose = AsyncMock()

    def snapshot(self):
        return self.options


@pytest.fixture
def pipeline(tmp_path):
    settings = Settings(_env_file=None)
    state = RuntimeState(personality_settings_path=tmp_path / "personalities.json")
    filters = FilterManager()
    provider = SyntheticProvider()
    return SharedAIService(settings, state, filters, provider=provider), provider


@pytest.mark.parametrize("search", [False, True])
async def test_every_provider_receives_shared_instructions_and_context(pipeline, search):
    service, provider = pipeline
    provider.capabilities = AIProviderCapabilities(search=search)
    service.settings.ai_response_language = ResponseLanguageSettings("limited", ("en",), "en")
    service.runtime_state.apply_profile_instructions("Use community vocabulary.")
    service.runtime_state.apply_ai_personality("custom", "Use a cheerful tone.")
    result = await service.generate_reply(
        "latest score", "PRIVATE-VIEWER-ID", "Untrusted history", "Untrusted category",
    )
    assert result == AIReply("A friendly answer.", True)
    request, options = provider.generate.call_args.args
    assert request.use_search is search
    assert request.content.endswith("latest score")
    assert request.content.index("Untrusted history") < request.content.index("Untrusted category")
    assert "Current user request (the task to answer" in request.content
    assert "untrusted metadata" in request.content
    instruction = request.system_instruction
    assert instruction.index("Never:") < instruction.index("Use community vocabulary.")
    assert instruction.endswith("Use a cheerful tone.")
    assert "policy: Limited" in instruction
    assert f"at or below {AI_MAX_RESPONSE_LENGTH} characters" in instruction
    assert "PRIVATE-VIEWER-ID" not in request.content + instruction
    assert options.model == "synthetic-primary"


@pytest.mark.parametrize("source", ["protected_policy", "editable_filter", "filter_timeout"])
async def test_full_output_is_checked_before_length_limit_for_every_provider(pipeline, monkeypatch, source):
    service, provider = pipeline
    ending = " system prompt" if source == "protected_policy" else " samplealias"
    provider.generate.return_value = AIProviderResponse("A friendly sentence. " * 30 + ending)
    if source == "editable_filter":
        service.filter_manager.add_blocked_word("samplealias")
    elif source == "filter_timeout":
        monkeypatch.setattr(service.filter_manager, "evaluate_message", lambda _: FilterEvaluation(False, "patterns", timed_out=True))
    reply = await service.generate_reply("hello", "viewer")
    assert reply.status == "output_blocked"
    assert reply.moderation_source == source
    assert reply.text == "" and not reply.is_available


@pytest.mark.parametrize("text", ["A complete sentence. " * 30, "🙂" * 300, "word " * 100, "  Short answer.  "])
async def test_length_and_whitespace_policy_runs_for_every_provider(pipeline, text):
    service, provider = pipeline
    provider.generate.return_value = AIProviderResponse(text)
    reply = await service.generate_reply("hello", "viewer")
    assert reply.is_available and reply.text
    assert len(reply.text) <= AI_MAX_RESPONSE_LENGTH
    assert text.strip().startswith(reply.text)
    assert reply.text == reply.text.strip()


@pytest.mark.parametrize("response,status", [
    (AIProviderResponse("  \n "), "api_error"),
    (AIProviderResponse("Partial response", safety_blocked=True), "output_blocked"),
    (AIProviderResponse("Private partial output", status="timeout"), "timeout"),
    (AIProviderResponse(status="api_error"), "api_error"),
    (AIProviderResponse(status="provider_unavailable"), "provider_unavailable"),
])
async def test_normalized_provider_results_never_publish_partial_failed_text(pipeline, response, status):
    service, provider = pipeline
    provider.generate.return_value = response
    reply = await service.generate_reply("hello", "viewer")
    assert reply.status == status
    assert reply.text == "" and not reply.is_available


@pytest.mark.parametrize("error,status", [
    (RuntimeError("PRIVATE-KEY PRIVATE-PAYLOAD"), "api_error"),
    (httpx.ReadTimeout("PRIVATE-KEY"), "timeout"),
    (TimeoutError("PRIVATE-KEY"), "timeout"),
])
async def test_unexpected_provider_failures_are_safe(pipeline, caplog, error, status):
    service, provider = pipeline
    provider.generate.side_effect = error
    with caplog.at_level(logging.INFO, logger="app.services.ai_service"):
        reply = await service.generate_reply("hello", "viewer")
    assert reply == AIReply("", False, status)
    assert "PRIVATE" not in str(reply) + caplog.text
    failure = next(record for record in caplog.records if getattr(record, "event_kind", None) == "ai.failure")
    assert failure.event_requested_model == "synthetic-primary"
    assert failure.event_requested_provider == "Synthetic provider"


async def test_shared_deadline_cancels_any_provider_and_cancellation_propagates(pipeline, monkeypatch):
    service, provider = pipeline
    cancelled = asyncio.Event()
    async def stall(*_):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    provider.generate.side_effect = stall
    monkeypatch.setattr("app.services.ai_service.AI_REQUEST_TIMEOUT_SECONDS", 0.02)
    assert (await service.generate_reply("hello", "viewer")).status == "timeout"
    assert cancelled.is_set()
    provider.generate.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await service.generate_reply("hello", "viewer")


async def test_availability_discovery_and_close_delegate_without_changing_preferences(pipeline):
    service, provider = pipeline
    provider.is_available = False
    assert not service.is_available
    assert await service.generate_reply("hello", "viewer") == AIReply("", False, "provider_unavailable")
    provider.generate.assert_not_awaited()
    with pytest.raises(RuntimeError, match="Configure the provider API key"):
        await service.discover_models()
    provider.is_available = True
    assert await service.discover_models() == ["synthetic-primary"]
    await service.aclose()
    provider.discover_models.assert_awaited_once()
    provider.aclose.assert_awaited_once()


def test_prepared_payloads_are_immutable_and_do_not_repr_private_values():
    options = AIProviderSettings("model", "fallback", SecretStr("PRIVATE-KEY"))
    request = AIGenerationRequest("PRIVATE-INSTRUCTIONS", "PRIVATE-QUESTION")
    response = AIProviderResponse("PRIVATE-REPLY")
    for value, attribute in [(options, "model"), (request, "content"), (response, "text")]:
        with pytest.raises(FrozenInstanceError):
            setattr(value, attribute, "changed")
        assert "PRIVATE" not in repr(value)


def test_legacy_settings_default_to_gemini_without_a_provider_field():
    settings = Settings(_env_file=None, gemini_api_key=None)
    service = SharedAIService(settings)
    assert isinstance(service.provider, GeminiProvider)
    assert not service.is_available


async def test_snapshot_precedes_client_wait_and_survives_settings_changes_and_fallback(tmp_path, monkeypatch):
    settings = Settings(_env_file=None, gemini_api_key="synthetic-first-key",
                        gemini_model="gemini-primary", gemini_fallback_model="gemini-backup")
    state = RuntimeState(personality_settings_path=tmp_path / "personalities.json")
    state.apply_profile_instructions("Original community vocabulary.")
    service = SharedAIService(settings, state)
    calls = []
    keys = []
    class MissingModel(Exception):
        code = 404
    async def generate(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise MissingModel()
        return SimpleNamespace(text="A friendly answer.", candidates=[])
    class Client:
        aio = SimpleNamespace(models=SimpleNamespace(generate_content=generate), aclose=AsyncMock())
        def close(self):
            pass
    def new_client(**kwargs):
        keys.append(kwargs["api_key"])
        return Client()
    from google import genai
    monkeypatch.setattr(genai, "Client", new_client)
    try:
        async with service.provider._client_condition:
            task = asyncio.create_task(service.generate_reply("latest score", "viewer", "Old history", "Old category"))
            await asyncio.sleep(0)
            assert not task.done()
            settings.gemini_api_key = SecretStr("synthetic-second-key")
            settings.gemini_model = "gemini-new"
            settings.gemini_fallback_model = "gemini-new-backup"
            settings.ai_response_language = ResponseLanguageSettings("limited", ("en",), "en")
            state.apply_profile_instructions("Updated vocabulary.")
            state.apply_ai_personality("custom", "Updated tone.")
        assert (await task).is_available
        assert keys == ["synthetic-first-key"]
        assert [call["model"] for call in calls] == ["gemini-primary", "gemini-backup"]
        assert calls[0]["contents"] == calls[1]["contents"]
        assert "Old history" in calls[0]["contents"] and "Old category" in calls[0]["contents"]
        instruction = calls[0]["config"].system_instruction
        assert instruction == calls[1]["config"].system_instruction
        assert "Original community vocabulary." in instruction and "Updated vocabulary." not in instruction
        assert "policy: Auto" in instruction
        assert (await service.generate_reply("hello", "viewer")).is_available
        assert keys == ["synthetic-first-key", "synthetic-second-key"]
        assert calls[-1]["model"] == "gemini-new"
        assert "Updated vocabulary." in calls[-1]["config"].system_instruction
        assert "policy: Limited" in calls[-1]["config"].system_instruction
    finally:
        await service.aclose()
