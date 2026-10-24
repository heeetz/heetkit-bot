"""Offline adapter checks for native thinking, safe final parts and attribution."""

from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from app.services.ai_provider import AIGenerationRequest, AIProviderSettings
from app.services.gemini_ai_service import GeminiProvider


def fake_provider(monkeypatch, *, parts=None, metadata=None, error=None):
    provider = GeminiProvider(SimpleNamespace(gemini_api_key=SecretStr("synthetic")))
    calls = []
    async def generate(**kwargs):
        calls.append(kwargs)
        if error is not None:
            raise error
        return SimpleNamespace(candidates=[SimpleNamespace(
            content=SimpleNamespace(parts=parts or [SimpleNamespace(text="Final answer", thought=False)]),
            finish_reason="STOP", grounding_metadata=metadata,
        )], text="PRIVATE CONVENIENCE ACCESSOR")
    @asynccontextmanager
    async def client(_key):
        yield SimpleNamespace(models=SimpleNamespace(generate_content=generate))
    monkeypatch.setattr(provider, "_provider_client", client)
    return provider, calls


@pytest.mark.parametrize("model,thinking,field,expected", [
    ("gemini-3.6-flash", "minimal", "thinking_level", "MINIMAL"),
    ("gemini-2.5-pro", "budget:32768", "thinking_budget", 32768),
    ("gemini-2.5-flash", "off", "thinking_budget", 0),
])
async def test_gemini_uses_only_actual_native_parameters(monkeypatch, model, thinking, field, expected):
    provider, calls = fake_provider(monkeypatch)
    options = AIProviderSettings(model, "gemini-3.1-flash-lite", SecretStr("synthetic"), thinking, True)
    result = await provider.generate(AIGenerationRequest("system", "question"), options)
    assert result.text == "Final answer"
    config = calls[0]["config"]
    actual = getattr(config.thinking_config, field)
    assert str(actual).rsplit(".", 1)[-1] == str(expected)
    assert config.thinking_config.include_thoughts is False
    assert config.temperature is None and config.top_p is None and config.top_k is None
    assert config.max_output_tokens >= (expected + 1024 if isinstance(expected, int) else 1024)
    await provider.aclose()


async def test_gemini_thoughts_are_excluded_and_grounding_remains_attributed(monkeypatch):
    metadata = SimpleNamespace(web_search_queries=["current query"],
        search_entry_point=SimpleNamespace(rendered_content="<div>required suggestions</div>"),
        grounding_chunks=[SimpleNamespace(web=SimpleNamespace(title="Source", uri="https://example.test/"))])
    provider, calls = fake_provider(monkeypatch, metadata=metadata, parts=[
        SimpleNamespace(text="PRIVATE THOUGHT", thought=True),
        SimpleNamespace(text="Final answer", thought=False),
    ])
    options = AIProviderSettings("gemini-3.6-flash", "gemini-3.1-flash-lite", SecretStr("synthetic"), "low", True)
    result = await provider.generate(AIGenerationRequest("system", "question", True), options)
    assert result.text == "Final answer"
    assert result.search_used and result.attribution_required
    assert result.sources[0].url == "https://example.test/"
    assert calls[0]["config"].tools[0].google_search is not None
    await provider.aclose()


async def test_gemini_single_attempt_reports_missing_model_without_internal_fallback(monkeypatch):
    error = type("MissingModel", (Exception,), {"code": 404})()
    provider, calls = fake_provider(monkeypatch, error=error)
    options = AIProviderSettings("gemini-3.6-flash", "gemini-3.1-flash-lite", SecretStr("synthetic"), single_attempt=True)
    result = await provider.generate(AIGenerationRequest("system", "question"), options)
    assert result.status == "model_unavailable"
    assert len(calls) == 1
    await provider.aclose()


async def test_gemini_stale_model_controls_fail_before_provider_call(monkeypatch):
    provider, calls = fake_provider(monkeypatch)
    options = AIProviderSettings("gemini-3.8-flash", "gemini-3.1-flash-lite", SecretStr("synthetic"), "off", True)
    assert (await provider.generate(AIGenerationRequest("s", "u"), options)).status == "configuration_error"
    assert calls == []
    unknown = replace(options, model="gemini-custom", thinking="default")
    assert (await provider.generate(AIGenerationRequest("s", "u", True), unknown)).status == "configuration_error"
    assert calls == []
    await provider.aclose()
