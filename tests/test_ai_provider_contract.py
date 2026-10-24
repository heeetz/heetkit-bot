"""Both real adapters obey shared policy with synthetic provider responses."""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.config.settings import Settings
from app.runtime_state import RuntimeState
from app.services.ai_service import SharedAIService
from app.services.filter_manager import FilterManager


@pytest.fixture(params=["gemini", "deepseek"])
async def provider_pipeline(request, tmp_path, monkeypatch):
    settings = Settings(ai_provider=request.param, gemini_api_key="PRIVATE-GEMINI-KEY",
                        deepseek_api_key="PRIVATE-DEEPSEEK-KEY")
    filters = FilterManager()
    state = RuntimeState(personality_settings_path=tmp_path / "personalities.json")
    state.apply_profile_instructions("PRIVATE-PROFILE-INSTRUCTIONS")
    service = SharedAIService(settings, state, filters)
    exchange = AsyncMock(return_value="A friendly answer.")
    calls = []
    if request.param == "gemini":
        from google import genai

        async def generate(**kwargs):
            calls.append((kwargs["config"].system_instruction, kwargs["contents"], kwargs["model"]))
            return SimpleNamespace(text=await exchange(), candidates=[])

        class Client:
            aio = SimpleNamespace(models=SimpleNamespace(generate_content=generate), aclose=AsyncMock())
            def close(self):
                pass

        monkeypatch.setattr(genai, "Client", lambda **kwargs: Client())
    else:
        async def http_json(method, path, key, **kwargs):
            payload = kwargs["json"]
            calls.append((payload["messages"][0]["content"], payload["messages"][1]["content"], payload["model"]))
            return 200, {"choices": [{"finish_reason": "stop", "message": {
                "content": await exchange(), "reasoning_content": "PRIVATE-THOUGHT"}}]}
        monkeypatch.setattr(service.provider, "_http_json", http_json)
    yield service, exchange, calls
    await service.aclose()


async def test_shared_prompt_context_bounds_and_private_diagnostics(provider_pipeline, caplog):
    service, exchange, calls = provider_pipeline
    exchange.return_value = "A friendly answer. " * 30
    with caplog.at_level(logging.INFO):
        reply = await service.generate_reply("PRIVATE-QUESTION", "PRIVATE-USER-ID", "PRIVATE-HISTORY", "PRIVATE-CATEGORY")
    assert reply.is_available and len(reply.text) <= 220
    instruction, content, model = calls[0]
    assert "PRIVATE-PROFILE-INSTRUCTIONS" in instruction
    assert all(value in content for value in ("PRIVATE-QUESTION", "PRIVATE-HISTORY", "PRIVATE-CATEGORY"))
    assert "PRIVATE-USER-ID" not in content
    assert model == getattr(service.settings, service.settings.ai_provider + "_model")
    assert "PRIVATE" not in caplog.text + str([vars(record) for record in caplog.records])


@pytest.mark.parametrize("suffix,source", [(" system prompt", "protected_policy"), (" blockedword", "editable_filter")])
async def test_complete_output_policy_precedes_truncation(provider_pipeline, suffix, source):
    service, exchange, _ = provider_pipeline
    service.filter_manager.add_blocked_word("blockedword")
    exchange.return_value = "A friendly answer. " * 30 + suffix
    reply = await service.generate_reply("hello", "viewer")
    assert reply.status == "output_blocked" and reply.moderation_source == source
    assert not reply.text and not reply.is_available


async def test_errors_and_cancellation_never_publish_private_output(provider_pipeline, caplog):
    service, exchange, _ = provider_pipeline
    exchange.side_effect = RuntimeError("PRIVATE-ERROR-PAYLOAD")
    assert (await service.generate_reply("hello", "viewer")).status == "api_error"
    exchange.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await service.generate_reply("hello", "viewer")
    assert "PRIVATE" not in caplog.text


async def test_provider_switch_keeps_inflight_adapter_and_snapshot(provider_pipeline):
    service, exchange, calls = provider_pipeline
    captured_provider = service.settings.ai_provider
    entered, release = asyncio.Event(), asyncio.Event()
    async def blocked():
        entered.set()
        await release.wait()
        return "Old request finished."
    exchange.side_effect = blocked
    pending = asyncio.create_task(service.generate_reply("hello", "viewer"))
    await entered.wait()
    service.settings.ai_provider = "deepseek" if captured_provider == "gemini" else "gemini"
    setattr(service.settings, captured_provider + "_api_key", None)
    release.set()
    assert (await pending).text == "Old request finished."
    assert len(calls) == 1 and calls[0][2] == getattr(service.settings, captured_provider + "_model")


@pytest.mark.parametrize("status,code", [(401, "credential_rejected"), (403, "credential_rejected"),
                                         (429, "rate_limited"), (500, "provider_error")])
async def test_discovery_errors_are_safe_and_do_not_change_models(provider_pipeline, monkeypatch, status, code):
    from app.services.ai_provider import AIModelDiscoveryError
    service, _, _ = provider_pipeline
    before = service.provider.snapshot()
    class ProviderError(RuntimeError):
        status_code = status
    async def reject():
        raise ProviderError("PRIVATE-PROVIDER-BODY")
    monkeypatch.setattr(service.provider, "discover_models", reject)
    with pytest.raises(AIModelDiscoveryError) as error:
        await service.discover_models()
    assert error.value.code == code and "PRIVATE" not in str(error.value)
    assert service.provider.snapshot() == before
