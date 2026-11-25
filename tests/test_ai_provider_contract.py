"""Both real adapters obey shared policy with synthetic provider responses."""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.config.ai_setup import AISetup, AIModelSelection
from app.config.ai_models import AIConnection
from app.config.settings import Settings
from app.services.custom_ai_service import final_answer
from app.runtime_state import RuntimeState
from app.services.ai_service import SharedAIService
from app.services.filter_manager import FilterManager
from app.config_file import ConfigFile


def _model(settings):
    if settings.ai_provider == "custom":
        return settings.ai_setup.primary.model
    return getattr(settings, settings.ai_provider + "_model")


@pytest.fixture(params=["gemini", "deepseek", "openai", "custom"])
async def provider_pipeline(request, tmp_path, monkeypatch):
    settings = Settings(ai_provider=request.param, gemini_api_key="PRIVATE-GEMINI-KEY",
                        deepseek_api_key="PRIVATE-DEEPSEEK-KEY", openai_api_key="PRIVATE-OPENAI-KEY")
    if request.param == "custom":
        # A local server without a key; the reply carries recognized reasoning to strip.
        settings.ai_connections = (AIConnection("custom", base_url="http://localhost:1234/v1"),)
        settings.ai_setup = AISetup(AIModelSelection("custom", "qwen/qwen3-27b@q4_k_m"))
    filters = FilterManager()
    state = RuntimeState(ConfigFile(tmp_path / "personalities.json"))
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
    elif request.param in {"deepseek", "custom"}:
        async def http_json(method, path, key, **kwargs):
            if request.param == "custom":
                assert key is None and kwargs["base_url"] == "http://localhost:1234/v1"
            payload = kwargs["json"]
            calls.append((payload["messages"][0]["content"], payload["messages"][1]["content"], payload["model"]))
            answer = await exchange()
            return 200, {"choices": [{"finish_reason": "stop", "message": {
                "content": "<think>PRIVATE-THOUGHT</think>" + answer if request.param == "custom" else answer,
                "reasoning_content": "PRIVATE-THOUGHT"}}]}
        monkeypatch.setattr(service.provider, "_http_json", http_json)
    else:
        async def http_json(method, path, key, **kwargs):
            payload = kwargs["json"]
            calls.append((payload["instructions"], payload["input"], payload["model"]))
            return 200, {"status": "completed", "model": payload["model"], "output": [
                {"type": "reasoning", "summary": [{"text": "PRIVATE-THOUGHT"}]},
                {"type": "message", "role": "assistant", "status": "completed", "content": [
                    {"type": "output_text", "text": await exchange(), "annotations": []}]}]}
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
    assert model == _model(service.settings)
    assert "PRIVATE-THOUGHT" not in reply.text
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
    service.settings.ai_provider = captured_provider
    assert len(calls) == 1 and calls[0][2] == _model(service.settings)


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


@pytest.mark.parametrize("content,answer", [
    ("<think>plan</think>\n Hello!", "Hello!"),
    ("<THINKING>a</THINKING>Hi <reasoning>b</reasoning>there", "Hi there"),
    ("<think>still thinking when the token limit hit", None),
    ("<think>only reasoning</think>  ", None),
    (None, None),
])
def test_custom_reply_is_only_final_answer_text(content, answer):
    assert final_answer(content) == answer


@pytest.mark.parametrize(("network", "private", "url", "answers", "expected"), [
    ("local", False, "http://localhost:{port}/v1", None, ["local-model"]),
    # A hand-edited Desktop profile cannot widen HTTP beyond this computer.
    ("local", False, "http://192.168.1.5:{port}/v1", None, "custom_address_refused"),
    ("private", True, "http://localhost:{port}/v1", None, ["local-model"]),
    # Server: the connection's switch opts in, the environment stays the ceiling.
    ("private", False, "http://localhost:{port}/v1", None, "custom_address_refused"),
    ("public", True, "http://localhost:{port}/v1", None, "custom_address_refused"),
    ("public", False, "https://llm.example.test/v1", ["10.0.0.5"], "custom_address_refused"),
    # Any disallowed answer refuses the name, including mapped cloud metadata.
    ("private", True, "https://llm.example.test/v1", ["93.184.216.34", "169.254.169.254"], "custom_address_refused"),
    ("local", True, "https://llm.example.test/v1", ["::ffff:169.254.169.254"], "custom_address_refused"),
])
async def test_custom_endpoint_connects_only_where_the_host_allows(unused_tcp_port, monkeypatch,
                                                                    network, private, url, answers, expected):
    from aiohttp import web
    from app.services.ai_provider import AIModelDiscoveryError

    async def models(request):
        return web.json_response({"data": [{"id": "local-model"}]})

    application = web.Application()
    application.router.add_get("/v1/models", models)
    runner = web.AppRunner(application)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", unused_tcp_port).start()
    if answers is not None:
        async def resolve(host, port, **kwargs):
            return [(None, None, None, "", (address, port)) for address in answers]
        monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    connection = AIConnection("custom", base_url=url.format(port=unused_tcp_port), private_network=private)
    service = SharedAIService(Settings(ai_connections=(connection,), custom_ai_network=network), None, FilterManager())
    try:
        if isinstance(expected, list):
            assert await service.discover_models("custom") == expected
        else:
            with pytest.raises(AIModelDiscoveryError) as error:
                await service.discover_models("custom")
            assert error.value.code == expected
    finally:
        await service.aclose()
        await runner.cleanup()
