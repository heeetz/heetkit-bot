"""Both hosts share isolated operator generation without viewer or Twitch state."""

import asyncio
import logging
from json import dumps
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import SecretStr

from app.commands.ai import register_ai_commands
from app.commands.registry import CommandContext, CommandRegistry
from app.config.ai_setup import AIModelSelection, AISetup
from app.config.settings import Settings
from app.runtime_state import RuntimeState
from app.services.ai_request_policy import AIRequestPolicy
from app.services.filter_manager import FilterEvaluation, FilterManager
from app.services.ai_service import SharedAIService
from app.services.ai_playground import AIPlayground
from app.twitch.events import ChatAuthor, IncomingChatMessage
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
    ai = SharedAIService(settings, runtime_state=state, filter_manager=filters)
    services = SimpleNamespace(
        ai=ai, filter_manager=filters, ai_request_policy=AIRequestPolicy(), runtime_state=state,
        memory=ForbiddenService(), users=ForbiddenService(), twitch=ForbiddenService(),
        ai_user_blocks=ForbiddenService(),
    )
    backend = SimpleNamespace(application=SimpleNamespace(
        settings=settings, services=services, dispatcher=ForbiddenService(), database=ForbiddenService(),
    ))
    backend.application.ai_playground = AIPlayground(settings, services)
    return WebUIBridge(backend), ai, generate, filters, state


async def run_prompt(bridge, prompt="Tell me a story"):
    started = await bridge._start_ai_playground(prompt)
    assert started["ok"]
    await bridge._backend.application.ai_playground.task
    return await bridge._get_ai_playground_result(started["request_id"])


@pytest.mark.parametrize("provider,model,thinking", [
    ("deepseek", "deepseek-flash", "off"),
    ("openai", "gpt-6-luna", "none"),
    ("gemini", "gemini-2.5-flash", "off"),
])
@pytest.mark.parametrize("prompt,enabled,required,query", [
    ("кто такой счилла братик, он киберспортик?", True, False, "Schilla esports player"),
    ("Who designed the Z1 computer?", True, False, "Z1 computer designer"),
    ("Could you look up who designed the Z1?", True, True, "Z1 computer designer"),
    ("Погугли, кто создал Z1", True, True, None),  # Provider skipped the explicit lookup.
    ("Hey, how are you?", True, False, None),
    ("Translate 'search for a game' into French", True, False, None),
    ("What is 24 + 18?", True, False, None),
    ("Look up who designed the Z1", False, False, None),
])
async def test_search_tools_and_attribution_through_ask_and_playground(
    playground, monkeypatch, provider, model, thinking, prompt, enabled, required, query,
):
    bridge, ai, generate, filters, _ = playground
    ai.settings.ai_setup = AISetup(AIModelSelection(provider, model, thinking, enabled))
    setattr(ai.settings, f"{provider}_api_key", SecretStr("synthetic-search-key"))
    answer, url = "Synthetic answer.", "https://example.test/fact"
    tool_queries = []

    def check_instruction(instruction, content):
        assert content.endswith(prompt)
        assert ("accounting for casual wording, typos" in instruction) is enabled
        assert ("explicitly requested a lookup" in instruction) is required

    if provider == "gemini":
        async def grounded_response(contents, config, **kwargs):
            check_instruction(config.system_instruction, contents)
            assert bool(config.tools) is enabled
            if enabled:
                assert config.tools[0].google_search is not None
            if query is None:
                return SimpleNamespace(text=answer, candidates=[])
            tool_queries.append(query)
            grounding = SimpleNamespace(web_search_queries=[query],
                grounding_chunks=[SimpleNamespace(web=SimpleNamespace(title="Example", uri=url))],
                search_entry_point=SimpleNamespace(rendered_content="<div>Required suggestions</div>"))
            return SimpleNamespace(candidates=[SimpleNamespace(grounding_metadata=grounding,
                finish_reason="STOP", content=SimpleNamespace(parts=[SimpleNamespace(text=answer)]))])

        generate.side_effect = grounded_response
    else:
        async def http_json(method, path, key, *, json, **kwargs):
            if path == "/v1/tools/search":
                tool_queries.append(json["query"])
                return 200, {"results": [{"title": "Example", "url": url, "snippet": "Synthetic evidence"}]}
            assert path == ("/responses" if provider == "openai" else "/chat/completions")
            assert ("tools" in json) is enabled
            if provider == "openai":
                check_instruction(json["instructions"], json["input"])
                assert json.get("tool_choice") == (("required" if required else "auto") if enabled else None)
                output = []
                annotations = []
                if query is not None:
                    tool_queries.append(query)
                    output.append({"type": "web_search_call", "status": "completed",
                                   "action": {"type": "search", "query": query}})
                    annotations.append({"type": "url_citation", "start_index": 0, "end_index": len(answer),
                                        "url": url, "title": "Example"})
                output.append({"type": "message", "role": "assistant", "content": [
                    {"type": "output_text", "text": answer, "annotations": annotations}]})
                return 200, {"status": "completed", "output": output}

            messages = json["messages"]
            check_instruction(messages[0]["content"], messages[1]["content"])
            if len(messages) > 2:
                assert "tool_choice" not in json
                assert messages[-1]["role"] == "tool" and url in messages[-1]["content"]
            else:
                assert ("tool_choice" in json) is required
                if required:
                    assert json["tool_choice"]["function"]["name"] == "search_web"
                if query is not None:
                    return 200, {"choices": [{"finish_reason": "tool_calls", "message": {"tool_calls": [
                        {"id": "search-1", "type": "function", "function": {
                            "name": "search_web", "arguments": dumps({"query": query})}}]}}]}
            return 200, {"choices": [{"finish_reason": "stop", "message": {"content": answer}}]}

        monkeypatch.setattr(ai.provider, "_http_json", http_json)

    expected_status = ("attribution_unavailable" if provider == "gemini" and query else
                       "search_error" if required and query is None else "success")
    expected_answer = f"{answer} {url}" if provider == "openai" and query else answer
    result = await run_prompt(bridge, prompt)
    assert result["status"] == expected_status
    assert result["generation"]["search_enabled"] is enabled
    assert result["generation"]["search_used"] is bool(query)
    assert result["text"] == (expected_answer if expected_status == "success" else "")

    respond = AsyncMock(return_value=SimpleNamespace(sent=True))
    message = IncomingChatMessage("testchannel", f"!ask {prompt}", ChatAuthor("1", "viewer"), respond)
    services = SimpleNamespace(ai=ai, ai_request_policy=AIRequestPolicy(), filter_manager=filters)
    context = CommandContext(message, services, logging.getLogger(__name__))
    registry = CommandRegistry()
    register_ai_commands(registry)
    command = registry.get("ask")
    assert command.pre_check(context, prompt)
    await command.handler(context, prompt)
    if expected_status == "success":
        respond.assert_awaited_once_with(f"@viewer {expected_answer}")
    else:
        respond.assert_not_awaited()
    assert tool_queries == ([query, query] if query else [])
    await ai.aclose()


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
        assert instruction.index(state.profile_instructions) < instruction.index("Use a cheerful tone.")
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
    assert bridge._backend.application.ai_playground.task is None
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
    assert not bridge._backend.application.ai_playground.task.done()  # Repeated Cancel must not interrupt lease cleanup.
    assert not (await bridge._start_ai_playground("duplicate during cleanup"))["ok"]
    release.set()
    await bridge._backend.application.ai_playground.task
    result = await bridge._get_ai_playground_result(first["request_id"])
    assert result["status"] == "cancelled"
    assert not result.get("text")
    assert not ai.provider._client_users[next(iter(ai.provider._client_users))]
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
    monkeypatch.setattr("app.services.ai_playground.AI_REQUEST_TIMEOUT_SECONDS", 0.02)
    assert (await run_prompt(bridge))["status"] == "timeout"
    assert cancelled.is_set()
    assert not bridge._backend.application.ai_playground.task.cancelled()
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


async def test_timeout_discards_response_when_provider_suppresses_cancellation(playground, monkeypatch):
    bridge, ai, generate, _, _ = playground
    cleaning, release = asyncio.Event(), asyncio.Event()
    async def stubborn(**kwargs):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cleaning.set()
            await release.wait()
            return SimpleNamespace(text="PRIVATE late response", candidates=[])
    generate.side_effect = stubborn
    monkeypatch.setattr("app.services.ai_playground.AI_REQUEST_TIMEOUT_SECONDS", 0.02)
    started = await bridge._start_ai_playground("Tell me a story")
    await asyncio.wait_for(cleaning.wait(), 1)
    assert not (await bridge._start_ai_playground("duplicate during cleanup"))["ok"]
    release.set()
    await bridge._backend.application.ai_playground.task
    result = await bridge._get_ai_playground_result(started["request_id"])
    assert result["status"] == "timeout" and "PRIVATE" not in str(result)
    await ai.aclose()


async def test_completed_result_expires_without_another_http_request(playground):
    import time
    bridge, ai, _, _, _ = playground
    control = bridge._backend.application.ai_playground
    started = control.start("Tell me a story", owner=b"session", expires_at=time.monotonic() + 0.05)
    await control.task
    assert control.get(started["request_id"], owner=b"session")["status"] == "success"
    await asyncio.sleep(0.06)
    with pytest.raises(ValueError):
        control.get(started["request_id"], owner=b"session")
    assert control.task is None
    await ai.aclose()


async def test_public_controls_submit_to_owner_loop_and_sanitize_failures(playground):
    bridge, ai, generate, _, _ = playground
    loop = asyncio.get_running_loop()
    bridge._backend.submit = lambda coroutine: asyncio.run_coroutine_threadsafe(coroutine, loop)
    started = await asyncio.to_thread(bridge.start_ai_playground, "Tell me a story")
    await bridge._backend.application.ai_playground.task
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


@pytest.mark.parametrize("provider,model,thinking,label", [("deepseek", "deepseek-v4-pro", "high", "DeepSeek"),
                                                          ("openai", "gpt-6-luna", "none", "OpenAI")])
@pytest.mark.parametrize("fallback", [False, True])
async def test_effective_provider_model_thinking_and_tool_outcome_are_shared(playground, fallback, provider, model, thinking, label):
    from app.services.ai_provider import AIProviderResponse

    bridge, ai, _, _, _ = playground
    ai.settings.ai_setup = AISetup(
        AIModelSelection(provider, model, thinking, True),
        AIModelSelection("gemini", "gemini-2.5-flash", "off", True),
        cross_provider_acknowledged=True,
    )
    ai.settings.deepseek_api_key = SecretStr("private-deepseek-key")
    ai.settings.openai_api_key = SecretStr("private-openai-key")
    response = AIProviderResponse("Fresh answer.", search_used=True)
    primary = ai._providers[provider].generate = AsyncMock(
        return_value=AIProviderResponse(status="model_unavailable") if fallback else response,
    )
    secondary = ai._providers["gemini"].generate = AsyncMock(
        return_value=AIProviderResponse("Grounded answer.", search_used=True, attribution_required=True),
    )
    result = await run_prompt(bridge, "What is the latest news?")
    assert result["status"] == ("attribution_unavailable" if fallback else "success")
    assert result["text"] == ("" if fallback else "Fresh answer.")
    details = result["generation"]
    assert details == {
        "provider": "Google Gemini" if fallback else label,
        "model": "gemini-2.5-flash" if fallback else model,
        "thinking": "off" if fallback else thinking, "fallback_used": fallback,
        "search_enabled": True, "search_requested": True, "search_used": True,
        "input_tokens": None, "output_tokens": None,
    }
    assert primary.call_args.args[1].thinking == thinking
    assert primary.call_args.args[0].use_search
    assert secondary.await_count == int(fallback)
    assert "private-deepseek-key" not in str(result)
    await ai.aclose()


async def test_core_shutdown_cancels_before_closing_provider_and_forgets_result(tmp_path, monkeypatch):
    from app.container import build_application

    monkeypatch.setenv("HEETKIT_DATA_DIR", str(tmp_path))
    app = build_application(Settings(_env_file=None, database_url="sqlite+aiosqlite:///:memory:"))
    entered, cancelled = asyncio.Event(), asyncio.Event()

    async def generate(**kwargs):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    app.ai_service.generate_reply = generate
    app.ai_service.aclose = AsyncMock(side_effect=lambda: cancelled.is_set() or pytest.fail("Provider closed before cancellation"))
    started = app.ai_playground.start("Tell me a story")
    await entered.wait()
    await app.shutdown()
    assert cancelled.is_set()
    with pytest.raises(ValueError):
        app.ai_playground.get(started["request_id"])
    assert not app.ai_playground.start("another")["ok"]
