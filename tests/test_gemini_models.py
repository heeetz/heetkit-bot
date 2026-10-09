"""Focused tests for Gemini model selection, discovery, and fallback policy."""

import asyncio
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from app.container import Application
from app.config.ai_models import (
    DEFAULT_GEMINI_FALLBACK_MODEL,
    GEMINI_MODEL_PRESETS,
    GEMINI_PROVIDER_NAME,
)
from app.services.gemini_ai_service import GeminiAIService


class FakeGeminiClient:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.aio = self
        self.models = self
        self.calls: list[tuple[str, object]] = []
        self.async_closed = False
        self.sync_closed = False

    async def list(self, *, config):
        async def models():
            yield SimpleNamespace(
                name="models/gemini-discovered",
                supported_actions=["generateContent"],
            )

        return models()

    async def generate_content(self, *, model: str, contents: str, config: object):
        self.calls.append((model, config))
        if model == "gemini-missing":
            raise ProviderError(404)
        return SimpleNamespace(text="A response.", candidates=[])

    async def aclose(self) -> None:
        self.async_closed = True

    def close(self) -> None:
        self.sync_closed = True


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


@pytest.mark.asyncio
async def test_discovery_and_generation_reuse_client_with_live_model_settings(monkeypatch) -> None:
    from google import genai

    clients: list[FakeGeminiClient] = []

    def create_client(*, api_key: str, **kwargs) -> FakeGeminiClient:
        client = FakeGeminiClient(api_key)
        clients.append(client)
        return client

    monkeypatch.setattr(genai, "Client", create_client)
    from app.config.settings import Settings
    settings = Settings(
        gemini_api_key=SecretStr("first-key"),
        gemini_model="gemini-missing",
        gemini_fallback_model="gemini-fallback",
    )
    service = GeminiAIService(settings)

    assert await service.discover_models() == ["gemini-discovered"]
    assert (await service.generate_reply("latest score", "user")).text == "A response."
    settings.gemini_model = "gemini-new"
    assert (await service.generate_reply("hello", "user")).text == "A response."

    assert len(clients) == 1
    assert [model for model, _ in clients[0].calls] == [
        "gemini-missing", "gemini-fallback", "gemini-new",
    ]
    assert clients[0].calls[0][1].tools is not None
    assert clients[0].calls[-1][1].tools is None
    await service.aclose()
    assert clients[0].async_closed and clients[0].sync_closed


@pytest.mark.asyncio
async def test_credential_rotation_waits_for_old_client_users(monkeypatch) -> None:
    from google import genai

    clients: list[FakeGeminiClient] = []

    def create_client(*, api_key: str, **kwargs) -> FakeGeminiClient:
        client = FakeGeminiClient(api_key)
        clients.append(client)
        return client

    monkeypatch.setattr(genai, "Client", create_client)
    settings = SimpleNamespace(gemini_api_key=SecretStr("first-key"))
    service = GeminiAIService(settings)

    async with service._provider_client():
        settings.gemini_api_key = SecretStr("second-key")
        async with service._provider_client():
            assert [client.api_key for client in clients] == ["first-key", "second-key"]
            assert not clients[0].async_closed
        assert not clients[0].async_closed
    assert clients[0].async_closed and clients[0].sync_closed
    assert not clients[1].async_closed

    await service.aclose()
    assert clients[1].async_closed and clients[1].sync_closed
    with pytest.raises(RuntimeError, match="shut down"):
        async with service._provider_client():
            pass


@pytest.mark.asyncio
async def test_application_shutdown_waits_for_gemini_and_closes_resources(monkeypatch) -> None:
    from google import genai

    client = FakeGeminiClient("key")
    monkeypatch.setattr(genai, "Client", lambda **kwargs: client)
    service = GeminiAIService(SimpleNamespace(gemini_api_key=SecretStr("key")))
    closed: list[str] = []

    class Resource:
        async def aclose(self) -> None:
            closed.append("http")

        async def close(self) -> None:
            closed.append("database")

    resource = Resource()
    application = Application(
        settings=SimpleNamespace(), database=resource, http_client=resource,
        ai_service=service, services=SimpleNamespace(), registry=SimpleNamespace(),
        dispatcher=SimpleNamespace(),
    )
    entered = asyncio.Event()
    release = asyncio.Event()

    async def use_client() -> None:
        async with service._provider_client():
            entered.set()
            await release.wait()

    request = asyncio.create_task(use_client())
    await entered.wait()
    shutdown = asyncio.create_task(application.shutdown())
    await asyncio.sleep(0)
    assert not shutdown.done()
    assert not client.async_closed
    release.set()
    await asyncio.gather(request, shutdown)
    assert client.async_closed and client.sync_closed
    assert closed == ["http", "database"]
