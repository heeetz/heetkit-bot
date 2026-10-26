"""Focused offline tests for the OpenAI Responses HTTP adapter."""

import asyncio
import json
import logging
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr

from app.services import openai_ai_service as openai
from app.services.ai_provider import AIGenerationRequest


def make_provider(key="synthetic-key"):
    return openai.OpenAIProvider(SimpleNamespace(
        openai_api_key=SecretStr(key) if key is not None else None,
        openai_model="gpt-6-luna",
        openai_fallback_model="gpt-6.1-sol",
        openai_thinking="default",
    ))


def wire_transport(monkeypatch, handler):
    requests = []

    async def capture(self, method, path, key, **kwargs):
        content = json.dumps(kwargs["json"]).encode() if "json" in kwargs else b""
        request = httpx.Request(
            method, openai.OPENAI_BASE_URL + path,
            headers={"Authorization": f"Bearer {key.get_secret_value()}"}, content=content,
        )
        requests.append(request)
        response = await handler(request)
        if response.status_code >= 400:
            try:
                return response.status_code, response.json()
            except ValueError:
                return response.status_code, None
        return response.status_code, response.json()

    monkeypatch.setattr(openai.OpenAIProvider, "_http_json", capture)
    return requests


def response(text="The final answer.", *, model="gpt-6-luna", annotations=None, output=None):
    if output is None:
        output = [{"type": "message", "role": "assistant", "status": "completed",
                   "content": [{"type": "output_text", "text": text,
                                "annotations": annotations or []}]}]
    return httpx.Response(200, json={
        "id": "resp_synthetic", "model": model, "status": "completed", "output": output,
        "usage": {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18},
    })


@pytest.mark.asyncio
async def test_responses_payload_is_bounded_private_and_uses_captured_key(monkeypatch):
    requests = wire_transport(monkeypatch, lambda _: asyncio.sleep(0, result=response()))
    provider = make_provider()
    opts = provider.snapshot()
    provider.settings.openai_api_key = SecretStr("rotated-key")
    result = await provider.generate(AIGenerationRequest("system prompt", "user prompt"), opts)

    assert result.text == "The final answer."
    assert result.input_tokens == 11 and result.output_tokens == 7
    assert result.effective_model == "gpt-6-luna"
    sent = requests[0]
    payload = json.loads(sent.content)
    assert sent.url == "https://api.openai.com/v1/responses"
    assert sent.headers["Authorization"] == "Bearer synthetic-key"
    assert payload["model"] == "gpt-6-luna"
    assert payload["instructions"] == "system prompt" and payload["input"] == "user prompt"
    assert payload["store"] is False and payload["max_output_tokens"] == 4096
    assert "conversation" not in payload and "background" not in payload


@pytest.mark.asyncio
async def test_none_reasoning_uses_small_output_bound(monkeypatch):
    requests = wire_transport(monkeypatch, lambda _: asyncio.sleep(0, result=response()))
    provider = make_provider()
    result = await provider.generate(
        AIGenerationRequest("s", "u"), replace(provider.snapshot(), thinking="none"),
    )
    assert result.status == "success"
    assert json.loads(requests[0].content)["max_output_tokens"] == 1024


@pytest.mark.asyncio
async def test_multi_part_text_and_reasoning_are_handled_without_returning_non_text(monkeypatch):
    output = [
        {"type": "reasoning", "summary": [{"type": "summary_text", "text": "PRIVATE reasoning"}]},
        {"type": "message", "role": "assistant", "status": "completed", "content": [
            {"type": "output_text", "text": "Part one. "},
            {"type": "output_text", "text": "Part two."},
        ]},
    ]
    wire_transport(monkeypatch, lambda _: asyncio.sleep(0, result=response(output=output)))
    result = await make_provider().generate(AIGenerationRequest("s", "u"), make_provider().snapshot())
    assert result.text == "Part one. Part two."
    assert "PRIVATE" not in result.text


@pytest.mark.asyncio
async def test_refusal_is_safety_blocked_without_refusal_body(monkeypatch):
    output = [{"type": "message", "role": "assistant", "status": "completed",
               "content": [{"type": "refusal", "refusal": "PRIVATE refusal detail"}]}]
    wire_transport(monkeypatch, lambda _: asyncio.sleep(0, result=response(output=output)))
    provider = make_provider()
    result = await provider.generate(AIGenerationRequest("s", "u"), provider.snapshot())
    assert result.safety_blocked and result.text == ""
    assert "PRIVATE" not in repr(result)


@pytest.mark.asyncio
async def test_content_filter_incomplete_is_safety_blocked(monkeypatch):
    filtered = {"status": "incomplete", "incomplete_details": {"reason": "content_filter"}, "output": []}
    wire_transport(monkeypatch, lambda _: asyncio.sleep(0, result=httpx.Response(200, json=filtered)))
    provider = make_provider()
    result = await provider.generate(AIGenerationRequest("s", "u"), provider.snapshot())
    assert result.safety_blocked and result.text == ""


@pytest.mark.asyncio
async def test_incomplete_billed_response_keeps_safe_usage_without_partial_text(monkeypatch, caplog):
    payload = {"status": "incomplete", "model": "gpt-6-luna",
               "incomplete_details": {"reason": "max_output_tokens"},
               "usage": {"input_tokens": 120, "output_tokens": 4096},
               "output": [{"type": "reasoning", "summary": [{"text": "PRIVATE provider content"}]}]}
    wire_transport(monkeypatch, lambda _: asyncio.sleep(0, result=httpx.Response(200, json=payload)))
    provider = make_provider()
    with caplog.at_level(logging.INFO):
        result = await provider.generate(AIGenerationRequest("s", "u"), provider.snapshot())
    assert result.status == "api_error" and not result.text
    assert result.effective_model == "gpt-6-luna"
    assert (result.input_tokens, result.output_tokens) == (120, 4096)
    finish = next(record for record in caplog.records if getattr(record, "event_kind", None) == "ai.request_finish")
    assert finish.event_input_tokens == 120 and finish.event_output_tokens == 4096
    assert "PRIVATE" not in str([vars(record) for record in caplog.records])


@pytest.mark.asyncio
@pytest.mark.parametrize("code,status", [
    ("model_not_found", "model_unavailable"), ("invalid_api_key", "api_error"),
    ("rate_limit_exceeded", "api_error"), ("server_error", "api_error"),
    (None, "api_error"),
])
async def test_http_failures_are_sanitized_and_only_model_not_found_is_classified(monkeypatch, code, status, caplog):
    async def handler(_request):
        return httpx.Response(404 if code in {"model_not_found", None} else 429,
                              json={"error": {"code": code, "message": "PRIVATE provider diagnostic"}})
    requests = wire_transport(monkeypatch, handler)
    provider = make_provider("synthetic-secret")
    result = await provider.generate(AIGenerationRequest("s", "u"), provider.snapshot())
    assert result.status == status and len(requests) == 1
    assert "PRIVATE" not in str(caplog.records) and "synthetic-secret" not in str(caplog.records)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    None, [], {"status": "failed", "output": []},
    {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}, "output": []},
    {"status": "completed", "output": "invalid"},
    {"status": "completed", "output": [{"type": "message", "role": "assistant", "content": "invalid"}]},
])
async def test_malformed_failed_or_incomplete_responses_do_not_return_partial_text(monkeypatch, payload):
    async def handler(_request):
        return httpx.Response(200, json=payload)
    wire_transport(monkeypatch, handler)
    provider = make_provider()
    result = await provider.generate(AIGenerationRequest("s", "u"), provider.snapshot())
    assert result.status == "api_error" and result.text == ""


@pytest.mark.asyncio
async def test_search_payload_tool_budget_and_valid_citations(monkeypatch):
    citation = {"type": "url_citation", "url": "https://example.test/a", "title": "Example",
                "start_index": 9, "end_index": 15}
    citation_again = {**citation, "start_index": 20, "end_index": 26}
    output = [
        {"type": "web_search_call", "status": "completed", "id": "ws_1"},
        {"type": "message", "role": "assistant", "status": "completed", "content": [
            {"type": "output_text", "text": "Verified result and result",
             "annotations": [citation, citation_again]},
        ]},
    ]
    requests = wire_transport(monkeypatch, lambda _: asyncio.sleep(0, result=response(output=output)))
    provider = make_provider()
    result = await provider.generate(AIGenerationRequest("s", "u", True), provider.snapshot())
    payload = json.loads(requests[0].content)
    assert payload["tools"] == [{"type": "web_search", "search_context_size": "low"}]
    assert payload["max_tool_calls"] == openai.OPENAI_MAX_TOOL_CALLS == 2
    assert result.search_used and result.inline_citations
    assert result.text == "Verified result https://example.test/a and result https://example.test/a"
    assert [(source.title, source.url) for source in result.sources] == [
        ("Example", "https://example.test/a"),
    ]


def test_native_citation_markers_become_inline_urls_without_removing_the_claim():
    text = "Фактcitesource0."
    citation = {"type": "url_citation", "url": "https://example.test/a", "title": "A",
                "start_index": 4, "end_index": len(text) - 1}
    payload = response(text, annotations=[citation]).json()
    payload["output"].insert(0, {"type": "web_search_call", "status": "completed"})
    answer, sources, used, blocked = make_provider()._parse_response(payload, search_requested=True)
    assert answer == "Факт https://example.test/a ."
    assert used and not blocked and sources[0].url == "https://example.test/a"


@pytest.mark.asyncio
@pytest.mark.parametrize("output", [
    [{"type": "web_search_call", "status": "failed"}],
    [{"type": "web_search_call", "status": "completed"}],
    [{"type": "web_search_call", "status": "completed"},
     {"type": "message", "role": "assistant", "status": "completed",
      "content": [{"type": "output_text", "text": "Answer", "annotations": [
          {"type": "url_citation", "url": "javascript:alert(1)", "title": "bad",
           "start_index": 0, "end_index": 6},
      ]}]}],
])
async def test_search_failure_missing_citations_or_invalid_citation_suppresses_answer(monkeypatch, output):
    wire_transport(monkeypatch, lambda _: asyncio.sleep(0, result=response(output=output)))
    provider = make_provider()
    result = await provider.generate(AIGenerationRequest("s", "u", True), provider.snapshot())
    assert result.status == "search_error" and result.text == "" and result.sources == ()


@pytest.mark.asyncio
@pytest.mark.parametrize("annotations", [
    [{"type": "url_citation", "url": "https://example.test/a", "title": "A",
      "start_index": 0, "end_index": 100}],
    [{"type": "url_citation", "url": "https://example.test/a", "title": "A",
      "start_index": 0, "end_index": 4},
     {"type": "url_citation", "url": "https://example.test/b", "title": "B",
      "start_index": 3, "end_index": 6}],
])
async def test_search_citations_with_invalid_or_overlapping_ranges_fail_closed(monkeypatch, annotations):
    output = [{"type": "web_search_call", "status": "completed"},
              {"type": "message", "role": "assistant", "status": "completed",
               "content": [{"type": "output_text", "text": "Answer", "annotations": annotations}]}]
    wire_transport(monkeypatch, lambda _: asyncio.sleep(0, result=response(output=output)))
    provider = make_provider()
    result = await provider.generate(AIGenerationRequest("s", "u", True), provider.snapshot())
    assert result.status == "search_error" and result.text == ""


@pytest.mark.asyncio
async def test_unexpected_search_call_without_search_request_is_rejected(monkeypatch):
    output = [{"type": "web_search_call", "status": "completed"},
              {"type": "message", "role": "assistant", "status": "completed",
               "content": [{"type": "output_text", "text": "Answer"}]}]
    wire_transport(monkeypatch, lambda _: asyncio.sleep(0, result=response(output=output)))
    provider = make_provider()
    result = await provider.generate(AIGenerationRequest("s", "u"), provider.snapshot())
    assert result.status == "search_error" and result.text == ""


@pytest.mark.asyncio
async def test_search_request_without_completed_search_call_is_rejected(monkeypatch):
    wire_transport(monkeypatch, lambda _: asyncio.sleep(0, result=response("Unverified answer")))
    provider = make_provider()
    result = await provider.generate(AIGenerationRequest("s", "u", True), provider.snapshot())
    assert result.status == "search_error" and result.text == ""


@pytest.mark.asyncio
async def test_search_bounds_reject_too_many_citations_and_calls(monkeypatch):
    citations = [{"type": "url_citation", "url": f"https://example.test/{n}", "title": str(n),
                  "start_index": n, "end_index": n + 1}
                 for n in range(openai.OPENAI_MAX_SOURCES + 1)]
    output = [{"type": "web_search_call", "status": "completed"},
              {"type": "message", "role": "assistant", "status": "completed",
               "content": [{"type": "output_text", "text": "x" * (openai.OPENAI_MAX_SOURCES + 1),
                            "annotations": citations}]}]
    wire_transport(monkeypatch, lambda _: asyncio.sleep(0, result=response(output=output)))
    provider = make_provider()
    result = await provider.generate(AIGenerationRequest("s", "u", True), provider.snapshot())
    assert result.status == "search_error" and result.text == ""


@pytest.mark.asyncio
async def test_discovery_is_bounded_and_model_ids_are_validated(monkeypatch):
    async def handler(request):
        assert request.method == "GET" and request.url.path == "/v1/models"
        return httpx.Response(200, json={"data": [
            {"id": "gpt-z"}, {"id": "gpt-a"}, {"id": "bad id"}, {"id": ""},
        ]})
    wire_transport(monkeypatch, handler)
    assert await make_provider().discover_models() == ["gpt-a", "gpt-z"]


@pytest.mark.asyncio
async def test_missing_key_makes_no_request_and_key_is_secret_str(monkeypatch):
    requests = wire_transport(monkeypatch, lambda _: asyncio.sleep(0, result=response()))
    for key in (None, "  "):
        provider = make_provider(key)
        assert not provider.is_available
        assert (await provider.generate(AIGenerationRequest("s", "u"), provider.snapshot())).status == "provider_unavailable"
        with pytest.raises(RuntimeError, match="key is not configured"):
            await provider.discover_models()
    assert requests == []


@pytest.mark.asyncio
async def test_generation_timeout_and_explicit_cancellation_release_active_lease(monkeypatch):
    entered = asyncio.Event()
    async def timeout(*_args, **_kwargs):
        entered.set()
        raise httpx.ReadTimeout("synthetic timeout")
    monkeypatch.setattr(openai.OpenAIProvider, "_http_json", timeout)
    provider = make_provider()
    result = await provider.generate(AIGenerationRequest("s", "u"), provider.snapshot())
    assert result.status == "timeout" and entered.is_set()
    await provider.aclose()


@pytest.mark.asyncio
async def test_close_waits_for_inflight_generation_and_cancellation_closes_transport(monkeypatch):
    entered, release, disconnected = asyncio.Event(), asyncio.Event(), asyncio.Event()
    async def handler(_request):
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            disconnected.set()
            raise
        return response()
    requests = wire_transport(monkeypatch, handler)
    provider = make_provider()
    task = asyncio.create_task(provider.generate(AIGenerationRequest("s", "u"), provider.snapshot()))
    await entered.wait()
    provider.settings.openai_api_key = SecretStr("rotated-key")
    closing = asyncio.create_task(provider.aclose())
    await asyncio.sleep(0)
    assert not closing.done()
    release.set()
    assert (await task).text == "The final answer."
    await closing
    assert requests[0].headers["Authorization"] == "Bearer synthetic-key"
    assert not provider.is_available

    provider2 = make_provider()
    cancellation_entered, disconnected = asyncio.Event(), asyncio.Event()
    async def stalled(_request):
        cancellation_entered.set()
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            disconnected.set()
            raise
    wire_transport(monkeypatch, stalled)
    task2 = asyncio.create_task(provider2.generate(AIGenerationRequest("s", "u"), provider2.snapshot()))
    await cancellation_entered.wait()
    task2.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task2
    assert disconnected.is_set()
    await provider2.aclose()


@pytest.mark.parametrize("oversized", [False, True])
@pytest.mark.asyncio
async def test_real_httpx_path_uses_fixed_host_no_redirects_no_env_and_response_limit(monkeypatch, oversized):
    original_client = httpx.AsyncClient
    clients = []
    def handler(request):
        assert str(request.url) == "https://api.openai.com/v1/responses"
        assert request.headers["Authorization"] == "Bearer synthetic-key"
        return (httpx.Response(200, content=b"x" * (openai.OPENAI_MAX_RESPONSE_BYTES + 1))
                if oversized else response())
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        created = original_client(**kwargs, transport=httpx.MockTransport(handler))
        clients.append(created)
        return created
    monkeypatch.setattr(httpx, "AsyncClient", client)
    provider = make_provider()
    result = await provider.generate(AIGenerationRequest("s", "u"), provider.snapshot())
    assert result.status == ("api_error" if oversized else "success")
    assert len(clients) == 1 and clients[0].is_closed
    await provider.aclose()
