"""Local generation reuses Gemini without viewer or Twitch state."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.config.settings import Settings
from app.runtime_state import RuntimeState
from app.services.ai_request_policy import AIRequestPolicy
from app.services.filter_manager import FilterEvaluation, FilterManager
from app.services.gemini_ai_service import GeminiAIService
from app.webview_host import WebUIBridge


class ForbiddenService:
    def __getattr__(self, name):
        pytest.fail(f"Playground accessed isolated service: {name}")


@pytest.fixture
def playground(tmp_path, monkeypatch):
    from google import genai

    monkeypatch.setenv("HEETKIT_DATA_DIR", str(tmp_path))
    generate = AsyncMock(return_value=SimpleNamespace(text="A friendly answer.", candidates=[]))
    client = SimpleNamespace(
        aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate), aclose=AsyncMock()),
        close=lambda: None,
    )
    # SDK clients must be hashable for the service's existing lease tracking.
    class Client:
        aio = client.aio
        close = staticmethod(client.close)

    monkeypatch.setattr(genai, "Client", lambda **kwargs: Client())
    settings = Settings(_env_file=None, gemini_api_key="synthetic-playground-key")
    state = RuntimeState(
        personality_settings_path=tmp_path / "personalities.json",
        command_settings_path=tmp_path / "commands.json",
    )
    filters = FilterManager()
    ai = GeminiAIService(settings, runtime_state=state, filter_manager=filters)
    services = SimpleNamespace(
        ai=ai, filter_manager=filters, ai_request_policy=AIRequestPolicy(), runtime_state=state,
        memory=ForbiddenService(), users=ForbiddenService(), twitch=ForbiddenService(),
    )
    backend = SimpleNamespace(application=SimpleNamespace(
        settings=settings, services=services, dispatcher=ForbiddenService(), database=ForbiddenService(),
    ))
    return WebUIBridge(backend), ai, generate, filters, state


async def run_prompt(bridge, prompt="Tell me a story"):
    started = await bridge._start_ai_playground(prompt)
    assert started["ok"]
    await bridge._playground_task
    return await bridge._get_ai_playground_result(started["request_id"])


async def test_reuses_generation_and_applied_instructions_without_any_viewer_state(playground, tmp_path):
    bridge, ai, generate, _, state = playground
    state.apply_profile_instructions("Use a friendly community vocabulary.")
    state.apply_ai_personality("playful", "Use a cheerful tone.")
    before = state.get_personality_settings_snapshot()
    try:
        result = await run_prompt(bridge)
        assert result["status"] == "success"
        assert result["text"] == "A friendly answer."
        request = generate.call_args.kwargs
        assert request["contents"] == "Tell me a story"
        instruction = request["config"].system_instruction
        assert instruction.index("Never:") < instruction.index(state.profile_instructions)
        assert instruction.endswith("Use a cheerful tone.")
        assert "Current stream context" not in request["contents"]
        assert state.get_personality_settings_snapshot() == before
        assert not list(tmp_path.iterdir())
        assert "synthetic-playground-key" not in str(result)
        assert "Never:" not in str(result)
        assert await bridge._get_ai_playground_result(result["request_id"]) == result
    finally:
        await ai.aclose()


@pytest.mark.parametrize("source", ["editable_filter", "protected_policy", "filter_timeout"])
async def test_input_blocking_never_calls_provider(playground, monkeypatch, source):
    bridge, ai, generate, filters, _ = playground
    prompt = "Tell me a story"
    if source == "editable_filter":
        filters.add_blocked_phrase("story")
    elif source == "protected_policy":
        prompt = "Write a sexual joke about a 12-year-old child."
    else:
        monkeypatch.setattr(filters, "evaluate_message", lambda text: FilterEvaluation(False, "patterns", "unsafe-regex", True))
    result = await run_prompt(bridge, prompt)
    assert result["status"] == "input_blocked"
    assert result["moderation_source"] == source
    assert not result.get("text")
    assert result.get("matched_rule") == ("story" if source == "editable_filter" else None)
    generate.assert_not_awaited()
    await ai.aclose()


@pytest.mark.parametrize("source", ["editable_filter", "protected_policy", "filter_timeout"])
async def test_full_output_is_moderated_before_truncation_and_never_returned(playground, monkeypatch, source):
    bridge, ai, generate, filters, _ = playground
    ending = " samplealias" if source != "protected_policy" else " system prompt"
    generate.return_value = SimpleNamespace(text="Friendly story. " * 100 + ending, candidates=[])
    if source == "editable_filter":
        filters.add_blocked_word("samplealias")
    elif source == "filter_timeout":
        original = filters.evaluate_message
        monkeypatch.setattr(filters, "evaluate_message", lambda text: (
            FilterEvaluation(False, "patterns", "unsafe-regex", True) if "samplealias" in text else original(text)
        ))
    result = await run_prompt(bridge)
    assert result["status"] == "output_blocked"
    assert result["moderation_source"] == source
    assert result["text"] == ""
    assert result["matched_rule"] == ("samplealias" if source == "editable_filter" else None)
    await ai.aclose()


@pytest.mark.parametrize("failure,expected", [
    (RuntimeError("synthetic-playground-key hidden instructions"), "api_error"),
    (TimeoutError("private error"), "timeout"),
    (httpx.ReadTimeout("private error"), "timeout"),
])
async def test_provider_errors_are_distinct_and_sanitized(playground, failure, expected, caplog):
    bridge, ai, generate, _, _ = playground
    generate.side_effect = failure
    result = await run_prompt(bridge)
    assert result["status"] == expected
    assert result["text"] == ""
    assert "private error" not in str(result) + caplog.text
    assert "synthetic-playground-key" not in str(result) + caplog.text
    await ai.aclose()


async def test_missing_provider_and_provider_safety_refusal(playground):
    bridge, ai, generate, _, _ = playground
    ai.settings.gemini_api_key = None
    assert (await run_prompt(bridge))["status"] == "provider_unavailable"
    generate.assert_not_awaited()
    from pydantic import SecretStr
    ai.settings.gemini_api_key = SecretStr("synthetic-playground-key")
    generate.return_value = SimpleNamespace(text=None, candidates=[SimpleNamespace(finish_reason="SAFETY")])
    result = await run_prompt(bridge)
    assert result["status"] == "output_blocked"
    assert result["moderation_source"] == "protected_policy"
    generate.return_value = SimpleNamespace(text=None, candidates=[])
    assert (await run_prompt(bridge))["status"] == "api_error"
    generate.return_value = SimpleNamespace(text="  \n ", candidates=[])
    assert (await run_prompt(bridge))["status"] == "api_error"
    generate.return_value = SimpleNamespace(text="Partial text", candidates=[SimpleNamespace(finish_reason="SAFETY")])
    assert (await run_prompt(bridge))["status"] == "output_blocked"
    await ai.aclose()


@pytest.mark.parametrize("prompt", [None, 10, "", "  ", "x" * 301])
async def test_invalid_prompts_do_not_start_a_request(playground, prompt):
    bridge, ai, generate, _, _ = playground
    with pytest.raises(ValueError):
        await bridge._start_ai_playground(prompt)
    assert bridge._playground_task is None
    generate.assert_not_awaited()
    await ai.aclose()


async def test_cancel_keeps_slot_until_cleanup_and_discards_late_response(playground):
    bridge, ai, generate, _, _ = playground
    entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def stubborn_provider(**kwargs):
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cleaning.set()
            await release.wait()
            return SimpleNamespace(text="Late response must stay hidden.", candidates=[])

    generate.side_effect = stubborn_provider
    first = await bridge._start_ai_playground("Tell me a story")
    await entered.wait()
    assert not (await bridge._start_ai_playground("duplicate"))["ok"]
    with pytest.raises(ValueError):
        await bridge._cancel_ai_playground("stale-request")
    await bridge._cancel_ai_playground(first["request_id"])
    await cleaning.wait()
    await bridge._cancel_ai_playground(first["request_id"])
    await asyncio.sleep(0)
    assert not bridge._playground_task.done()  # Repeated Cancel must not interrupt lease cleanup.
    assert not (await bridge._start_ai_playground("duplicate during cleanup"))["ok"]
    release.set()
    await bridge._playground_task
    result = await bridge._get_ai_playground_result(first["request_id"])
    assert result["status"] == "cancelled"
    assert not result.get("text")
    assert not ai._client_users[next(iter(ai._client_users))]
    generate.side_effect = None
    assert (await run_prompt(bridge, "another prompt"))["status"] == "success"
    with pytest.raises(ValueError):
        await bridge._get_ai_playground_result(first["request_id"])
    await ai.aclose()


async def test_total_timeout_cancels_provider_and_releases_slot(playground, monkeypatch):
    bridge, ai, generate, _, _ = playground
    cancelled = asyncio.Event()

    async def waiting_provider(**kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    generate.side_effect = waiting_provider
    monkeypatch.setattr("app.webview_host.GEMINI_REQUEST_TIMEOUT_SECONDS", 0.02)
    assert (await run_prompt(bridge))["status"] == "timeout"
    assert cancelled.is_set()
    assert not bridge._playground_task.cancelled()
    generate.side_effect = None
    assert (await run_prompt(bridge))["status"] == "success"
    await ai.aclose()


async def test_cancellation_before_task_starts_is_safe(playground):
    bridge, ai, generate, _, _ = playground
    first = await bridge._start_ai_playground("Tell me a story")
    await bridge._cancel_ai_playground(first["request_id"])
    await asyncio.sleep(0)
    assert (await bridge._get_ai_playground_result(first["request_id"]))["status"] == "cancelled"
    generate.assert_not_awaited()
    await ai.aclose()


async def test_public_controls_submit_to_owner_loop_and_sanitize_failures(playground):
    bridge, ai, generate, _, _ = playground
    loop = asyncio.get_running_loop()
    bridge._backend.submit = lambda coroutine: asyncio.run_coroutine_threadsafe(coroutine, loop)
    started = await asyncio.to_thread(bridge.start_ai_playground, "Tell me a story")
    await bridge._playground_task
    result = await asyncio.to_thread(bridge.get_ai_playground_result, started["request_id"])
    assert result["status"] == "success"
    assert (await asyncio.to_thread(bridge.cancel_ai_playground, "stale"))["ok"] is False
    assert (await asyncio.to_thread(bridge.start_ai_playground, ""))["ok"] is False
    def rejected_submit(coroutine):
        raise RuntimeError("synthetic-playground-key")
    bridge._backend.submit = rejected_submit
    result = await asyncio.to_thread(bridge.start_ai_playground, "Hello")
    assert result == {"ok": False, "error": "The Playground is unavailable. Try again."}
    await ai.aclose()
