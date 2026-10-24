"""Focused offline tests for the DeepSeek HTTP adapter."""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr

from app.services import deepseek_ai_service as deepseek
from app.services.ai_provider import AIGenerationRequest


def make_provider(key="synthetic-key"):
    settings = SimpleNamespace(
        deepseek_api_key=SecretStr(key) if key is not None else None,
        deepseek_model="deepseek-flash",
        deepseek_fallback_model="deepseek-v4-pro",
    )
    return deepseek.DeepSeekProvider(settings)


def wire_transport(monkeypatch, handler):
    requests = []

    async def capture(self, method, path, key, **kwargs):
        content = json.dumps(kwargs["json"]).encode() if "json" in kwargs else b""
        request = httpx.Request(
            method, deepseek.DEEPSEEK_BASE_URL + path,
            headers={"Authorization": f"Bearer {key.get_secret_value()}"}, content=content,
        )
        requests.append(request)
        response = await handler(request)
        if response.status_code >= 400:
            return response.status_code, None
        return response.status_code, response.json()

    monkeypatch.setattr(deepseek.DeepSeekProvider, "_http_json", capture)
    return requests


def completion(content="The final answer.", finish="stop", reasoning="private reasoning"):
    return httpx.Response(200, json={
        "choices": [{"message": {"role": "assistant", "content": content,
                                   "reasoning_content": reasoning},
                     "finish_reason": finish}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 4, "total_tokens": 9},
    })


@pytest.mark.asyncio
async def test_payload_uses_prepared_messages_disabled_thinking_and_final_content(monkeypatch):
    async def handler(request):
        return completion()

    requests = wire_transport(monkeypatch, handler)
    provider = make_provider()
    result = await provider.generate(
        AIGenerationRequest("system prompt", "user prompt"), provider.snapshot(),
    )

    assert result.text == "The final answer."
    sent = requests[0]
    payload = json.loads(sent.content)
    assert sent.url == "https://api.deepseek.com/chat/completions"
    assert sent.headers["Authorization"] == "Bearer synthetic-key"
    assert payload == {
        "model": "deepseek-flash",
        "messages": [{"role": "system", "content": "system prompt"},
                     {"role": "user", "content": "user prompt"}],
        "thinking": {"type": "disabled"}, "stream": False, "max_tokens": 1024,
    }
    assert "reasoning" not in result.text.lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("finish,content", [("length", "partial"), ("tool_calls", "partial"),
                                           ("stop", " ")])
async def test_suppresses_partial_tool_and_empty_outputs(monkeypatch, finish, content):
    wire_transport(monkeypatch, lambda _: asyncio.sleep(0, result=completion(content, finish)))
    provider = make_provider()
    result = await provider.generate(AIGenerationRequest("s", "u"), provider.snapshot())
    assert result.text == ""
    assert result.status == "api_error"


@pytest.mark.asyncio
async def test_falls_back_only_for_missing_primary_model(monkeypatch):
    async def handler(request):
        if json.loads(request.content)["model"] == "deepseek-flash":
            return httpx.Response(404, json={"error": {"message": "private server details"}})
        return completion("fallback answer")

    requests = wire_transport(monkeypatch, handler)
    provider = make_provider()
    result = await provider.generate(AIGenerationRequest("s", "u"), provider.snapshot())
    assert result.text == "fallback answer"
    assert [json.loads(request.content)["model"] for request in requests] == [
        "deepseek-flash", "deepseek-v4-pro",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [401, 403, 429, 500])
async def test_auth_rate_and_server_errors_do_not_fallback_or_leak_payload(monkeypatch, caplog, code):
    wire_transport(monkeypatch, lambda _: asyncio.sleep(
        0, result=httpx.Response(code, json={"error": {"message": "private provider body"}}),
    ))
    provider = make_provider("synthetic-secret")
    result = await provider.generate(AIGenerationRequest("s", "u"), provider.snapshot())
    assert result.status == "api_error"
    assert len(caplog.records) <= 1
    assert "private" not in str(caplog.records).lower()
    assert "synthetic-secret" not in str(caplog.records)


@pytest.mark.asyncio
async def test_discovery_uses_bearer_key_bounds_and_sorts_models(monkeypatch):
    async def handler(request):
        assert request.method == "GET"
        assert request.url.path == "/models"
        assert request.headers["Authorization"] == "Bearer synthetic-key"
        return httpx.Response(200, json={"data": [
            {"id": "deepseek-z"}, {"id": "deepseek-a"}, {"id": "gemini-unsafe"},
            {"id": "deepseek-" + "x" * 130}, {"id": 42},
        ]})

    wire_transport(monkeypatch, handler)
    provider = make_provider()
    assert await provider.discover_models() == ["deepseek-a", "deepseek-z"]


@pytest.mark.asyncio
@pytest.mark.parametrize("data", [[], [{"id": "gemini-unsafe"}, {"id": "bad/id"}]])
async def test_discovery_returns_empty_for_empty_or_foreign_model_lists(monkeypatch, data):
    wire_transport(monkeypatch, lambda _: asyncio.sleep(0, result=httpx.Response(200, json={"data": data})))
    assert await make_provider().discover_models() == []


@pytest.mark.asyncio
async def test_discovery_truncates_after_bounded_number_of_entries(monkeypatch):
    monkeypatch.setattr(deepseek, "DEEPSEEK_MAX_DISCOVERED_MODELS", 2)
    data = [{"id": "deepseek-first"}, {"id": "deepseek-second"}, {"id": "deepseek-third"}]
    wire_transport(monkeypatch, lambda _: asyncio.sleep(0, result=httpx.Response(200, json={"data": data})))
    assert await make_provider().discover_models() == ["deepseek-first", "deepseek-second"]


@pytest.mark.asyncio
async def test_missing_or_blank_key_is_unavailable_and_discovery_makes_no_request(monkeypatch):
    requests = wire_transport(monkeypatch, lambda _: asyncio.sleep(0, result=completion()))
    for key in (None, "  "):
        provider = make_provider(key)
        assert not provider.is_available
        assert (await provider.generate(AIGenerationRequest("s", "u"), provider.snapshot())).status == "provider_unavailable"
        with pytest.raises(RuntimeError, match="key is not configured"):
            await provider.discover_models()
    assert requests == []


@pytest.mark.asyncio
async def test_search_request_is_refused_without_transport(monkeypatch):
    requests = wire_transport(monkeypatch, lambda _: asyncio.sleep(0, result=completion()))
    provider = make_provider()
    result = await provider.generate(
        AIGenerationRequest("s", "u", use_search=True), provider.snapshot(),
    )
    assert result.status == "provider_unavailable"
    assert requests == []


@pytest.mark.asyncio
async def test_snapshot_keeps_old_key_during_rotation_and_close_drains_call(monkeypatch):
    entered = asyncio.Event()
    release = asyncio.Event()
    keys = []

    async def handler(request):
        keys.append(request.headers["Authorization"])
        if len(keys) == 1:
            entered.set()
            await release.wait()
        return completion()

    requests = wire_transport(monkeypatch, handler)
    provider = make_provider("synthetic-old")
    old_snapshot = provider.snapshot()
    task = asyncio.create_task(provider.generate(AIGenerationRequest("s", "u"), old_snapshot))
    await entered.wait()
    provider.settings.deepseek_api_key = SecretStr("synthetic-new")
    assert provider.snapshot().api_key == SecretStr("synthetic-new")
    closing = asyncio.create_task(provider.aclose())
    await asyncio.sleep(0)
    assert not closing.done()
    release.set()
    assert (await task).text == "The final answer."
    await closing
    assert keys == ["Bearer synthetic-old"]
    assert len(requests) == 1
    assert not provider.is_available


@pytest.mark.asyncio
async def test_cancellation_and_total_deadline_close_transport(monkeypatch):
    monkeypatch.setattr(deepseek, "DEEPSEEK_REQUEST_TIMEOUT_SECONDS", 0.05)
    entered = asyncio.Event()
    disconnected = asyncio.Event()

    async def handler(request):
        entered.set()
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            disconnected.set()
            raise

    wire_transport(monkeypatch, handler)
    provider = make_provider()
    result = await provider.generate(AIGenerationRequest("s", "u"), provider.snapshot())
    assert result.status == "timeout"
    await entered.wait()
    assert disconnected.is_set()
    await provider.aclose()


@pytest.mark.asyncio
async def test_explicit_cancellation_releases_operation_and_closes_provider(monkeypatch):
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def handler(request):
        entered.set()
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    wire_transport(monkeypatch, handler)
    provider = make_provider()
    task = asyncio.create_task(provider.generate(AIGenerationRequest("s", "u"), provider.snapshot()))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled.is_set()
    await provider.aclose()
    assert not provider.is_available


@pytest.mark.asyncio
async def test_oversized_response_is_rejected(monkeypatch):
    async def oversized(*_args, **_kwargs):
        raise ValueError("DeepSeek response exceeded the size limit.")

    monkeypatch.setattr(deepseek.DeepSeekProvider, "_http_json", oversized)
    provider = make_provider()
    result = await provider.generate(AIGenerationRequest("s", "u"), provider.snapshot())
    assert result.status == "api_error"


@pytest.mark.parametrize("oversized", [False, True])
async def test_real_httpx_path_uses_fixed_host_limits_and_closes_client(monkeypatch, oversized):
    original_client = httpx.AsyncClient
    clients = []
    def handler(request):
        assert str(request.url) == "https://api.deepseek.com/chat/completions"
        assert request.headers["Authorization"] == "Bearer synthetic-key"
        if oversized:
            return httpx.Response(200, content=b"x" * (deepseek.DEEPSEEK_MAX_RESPONSE_BYTES + 1))
        return completion()
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        assert kwargs["timeout"].read == deepseek.DEEPSEEK_TRANSPORT_TIMEOUT_SECONDS
        created = original_client(**kwargs, transport=httpx.MockTransport(handler))
        clients.append(created)
        return created
    monkeypatch.setattr(httpx, "AsyncClient", client)
    provider = make_provider()
    result = await provider.generate(AIGenerationRequest("s", "u"), provider.snapshot())
    assert result.status == ("api_error" if oversized else "success")
    assert len(clients) == 1 and clients[0].is_closed
    await provider.aclose()
