"""Numeric usage accounting uses synthetic payloads, including unsuccessful rounds."""

import logging
from dataclasses import replace
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from app.services.ai_provider import (
    AIGenerationRequest, UsageAccumulator, normalized_usage,
)
from app.services.deepseek_ai_service import DeepSeekProvider
from app.services.openai_ai_service import OpenAIProvider


def test_missing_usage_is_unknown_and_invalid_values_are_not_counts():
    assert normalized_usage("openai", {}) == {"usage_incomplete": True}
    usage = normalized_usage("deepseek", {"usage": {
        "prompt_tokens": True, "completion_tokens": -1, "total_tokens": 2**64,
        "prompt_cache_hit_tokens": 0,
    }})
    assert usage == {"cached_input_tokens": 0, "usage_incomplete": True}


def test_cache_and_reasoning_are_subsets_and_gemini_tool_input_is_included():
    usage = normalized_usage("openai", {"usage": {
        "input_tokens": 100, "output_tokens": 30, "total_tokens": 130,
        "input_tokens_details": {"cached_tokens": 80},
        "output_tokens_details": {"reasoning_tokens": 20},
    }})
    assert usage == {"input_tokens": 100, "output_tokens": 30, "total_tokens": 130,
                     "cached_input_tokens": 80, "reasoning_tokens": 20, "usage_incomplete": False}
    gemini = normalized_usage("gemini", SimpleNamespace(usage_metadata=SimpleNamespace(
        prompt_token_count=100, tool_use_prompt_token_count=40, candidates_token_count=10,
        thoughts_token_count=20, cached_content_token_count=80, total_token_count=170,
    )))
    assert gemini["input_tokens"] == 140 and gemini["output_tokens"] == 30
    assert gemini["cached_input_tokens"] == 80 and gemini["reasoning_tokens"] == 20
    assert gemini["tool_input_tokens"] == 40 and gemini["usage_incomplete"] is False


def test_partial_rounds_retain_reported_usage_and_mark_omissions():
    usage = UsageAccumulator()
    usage.add(normalized_usage("deepseek", {"usage": {"prompt_tokens": 10, "completion_tokens": 5}}))
    usage.add(normalized_usage("deepseek", {"usage": {"prompt_tokens": 3}}))
    assert usage.metadata() == {"input_tokens": 13, "output_tokens": 5, "usage_incomplete": True}
    assert UsageAccumulator().metadata() == {"usage_incomplete": True}


@pytest.mark.asyncio
async def test_deepseek_failed_search_continuation_preserves_all_reported_usage(monkeypatch, caplog):
    provider = DeepSeekProvider(SimpleNamespace(
        deepseek_api_key=SecretStr("synthetic"), deepseek_model="deepseek-flash",
        deepseek_fallback_model="deepseek-flash",
    ))
    rounds = iter([
        (200, {"choices": [{"message": {"content": None, "tool_calls": [{
            "id": "transient", "type": "function", "function": {"name": "search_web", "arguments": "{}"},
        }]}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5, "prompt_cache_hit_tokens": 4}}),
        (500, {"usage": {"prompt_tokens": 3, "completion_tokens": 2}}),
    ])

    async def http(*args, **kwargs):
        return next(rounds)

    async def search(*args):
        return {}, []

    monkeypatch.setattr(provider, "_http_json", http)
    monkeypatch.setattr(provider, "_run_search_tool", search)
    with caplog.at_level(logging.INFO):
        result = await provider.generate(AIGenerationRequest("private", "private", use_search=True),
                                         replace(provider.snapshot(), single_attempt=True))
    assert result.status == "search_error"
    assert (result.input_tokens, result.output_tokens, result.cached_input_tokens) == (13, 7, 4)
    finish = [r for r in caplog.records if getattr(r, "event_kind", None) == "ai.request_finish"]
    assert len(finish) == 1 and finish[0].event_input_tokens == 13
    assert finish[0].event_outcome != "generated"
    assert result.usage_incomplete  # The second round did not report its cache breakdown.


@pytest.mark.asyncio
async def test_openai_http_error_usage_reaches_attempt_event(monkeypatch, caplog):
    provider = OpenAIProvider(SimpleNamespace(openai_api_key=SecretStr("synthetic"),
                                            openai_model="gpt-5-mini", openai_fallback_model="gpt-5-mini"))

    async def http(*args, **kwargs):
        return 500, {"usage": {"input_tokens": 7, "output_tokens": 2}, "private": "never retained"}

    monkeypatch.setattr(provider, "_http_json", http)
    with caplog.at_level(logging.INFO):
        result = await provider.generate(AIGenerationRequest("private", "private"), provider.snapshot())
    assert result.status == "api_error"
    finish = next(r for r in caplog.records if getattr(r, "event_kind", None) == "ai.request_finish")
    assert (finish.event_input_tokens, finish.event_output_tokens) == (7, 2)
    assert "never retained" not in caplog.text
