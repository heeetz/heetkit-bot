"""Focused tests for Gemini model selection, discovery, and fallback policy."""

from types import SimpleNamespace

import pytest

from app.config.ai_models import (
    DEFAULT_GEMINI_FALLBACK_MODEL,
    GEMINI_MODEL_PRESETS,
    GEMINI_PROVIDER_NAME,
)
from app.services.gemini_ai_service import GeminiAIService


def test_tracked_gemini_presets_include_the_default_fallback() -> None:
    assert GEMINI_PROVIDER_NAME == "Google Gemini"
    assert DEFAULT_GEMINI_FALLBACK_MODEL in {
        preset.id for preset in GEMINI_MODEL_PRESETS
    }


def test_model_discovery_keeps_only_text_generation_models() -> None:
    text_model = SimpleNamespace(
        name="models/gemini-custom",
        supported_actions=["generateContent"],
    )
    embedding_model = SimpleNamespace(
        name="models/gemini-embedding-001",
        supported_actions=["generateContent"],
    )
    unsupported_model = SimpleNamespace(
        name="models/gemini-other",
        supported_actions=["embedContent"],
    )

    assert GeminiAIService._normalize_discovered_model(text_model) == "gemini-custom"
    assert GeminiAIService._normalize_discovered_model(embedding_model) is None
    assert GeminiAIService._normalize_discovered_model(unsupported_model) is None


class ProviderError(Exception):
    def __init__(self, code: int) -> None:
        super().__init__(f"provider error {code}")
        self.code = code


@pytest.mark.asyncio
async def test_unavailable_selected_model_uses_configured_fallback() -> None:
    service = GeminiAIService(
        SimpleNamespace(
            gemini_model="gemini-selected",
            gemini_fallback_model="gemini-fallback",
        )
    )
    requested: list[str] = []

    async def request(model: str) -> str:
        requested.append(model)
        if model == "gemini-selected":
            raise ProviderError(404)
        return "fallback response"

    response, effective_model = await service._request_with_model_fallback(request)

    assert response == "fallback response"
    assert effective_model == "gemini-fallback"
    assert requested == ["gemini-selected", "gemini-fallback"]


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [ProviderError(401), ProviderError(403), ProviderError(429), OSError("network")])
async def test_auth_policy_rate_and_network_errors_do_not_use_fallback(error) -> None:
    service = GeminiAIService(
        SimpleNamespace(
            gemini_model="gemini-selected",
            gemini_fallback_model="gemini-fallback",
        )
    )
    requested: list[str] = []

    async def request(model: str) -> str:
        requested.append(model)
        raise error

    with pytest.raises(type(error)):
        await service._request_with_model_fallback(request)

    assert requested == ["gemini-selected"]
