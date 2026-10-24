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
from app.services.gemini_ai_service import GeminiProvider
from app.services.ai_service import SharedAIService


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

    assert GeminiProvider._normalize_discovered_model(text_model) == "gemini-custom"
    assert GeminiProvider._normalize_discovered_model(embedding_model) is None
    assert GeminiProvider._normalize_discovered_model(unsupported_model) is None


async def test_discovery_stops_after_bounded_model_count(monkeypatch):
    from contextlib import asynccontextmanager
    from app.services import gemini_ai_service
    monkeypatch.setattr(gemini_ai_service, "GEMINI_MAX_DISCOVERED_MODELS", 2)
    visited = []
    async def listing(**kwargs):
        async def models():
            for name in ("gemini-first", "gemini-second", "gemini-third"):
                visited.append(name)
                yield SimpleNamespace(name=name, supported_actions=["generateContent"])
        return models()
    @asynccontextmanager
    async def client(*args):
        yield SimpleNamespace(models=SimpleNamespace(list=listing))
    service = GeminiProvider(SimpleNamespace())
    monkeypatch.setattr(service, "_provider_client", client)
    assert await service.discover_models() == ["gemini-first", "gemini-second"]
    assert visited == ["gemini-first", "gemini-second"]


class ProviderError(Exception):
    def __init__(self, code: int) -> None:
        super().__init__(f"provider error {code}")
        self.code = code


@pytest.mark.asyncio
async def test_unavailable_selected_model_uses_configured_fallback() -> None:
    service = GeminiProvider(
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

    response, effective_model = await service._request_with_model_fallback(request, service.snapshot())

    assert response == "fallback response"
    assert effective_model == "gemini-fallback"
    assert requested == ["gemini-selected", "gemini-fallback"]


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [ProviderError(401), ProviderError(403), ProviderError(429), OSError("network")])
async def test_auth_policy_rate_and_network_errors_do_not_use_fallback(error) -> None:
    service = GeminiProvider(
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
        await service._request_with_model_fallback(request, service.snapshot())

    assert requested == ["gemini-selected"]


@pytest.mark.asyncio
async def test_attempt_events_capture_effective_model_usage_and_snapshot_without_payloads(caplog):
    import logging
    from app.utils.logging import operator_event_scope

    settings = SimpleNamespace(gemini_model="gemini-selected", gemini_fallback_model="gemini-fallback")
    service = GeminiProvider(settings)
    async def request(model):
        if model == "gemini-selected":
            settings.gemini_model = "gemini-changed"
            settings.gemini_fallback_model = "gemini-changed-fallback"
            raise ProviderError(404)
        assert model == "gemini-fallback"
        return SimpleNamespace(text="PRIVATE-RESPONSE", thoughts="PRIVATE-REASONING",
                               usage_metadata=SimpleNamespace(prompt_token_count=11,
                                   candidates_token_count=7, total_token_count=19,
                                   secret="PRIVATE-KEY"))
    with caplog.at_level(logging.INFO, logger="app.services.gemini_ai_service"):
        with operator_event_scope(request_id="r" * 32, channel="channel"):
            await service._request_with_model_fallback(request, service.snapshot())
    events = [record for record in caplog.records if hasattr(record, "event_kind")]
    assert len({record.event_event_id for record in events}) == len(events)
    assert all(record.event_request_id == "r" * 32 for record in events)
    assert all(record.event_requested_model == "gemini-selected" for record in events)
    assert all(record.event_requested_provider == record.event_provider == "Google Gemini" for record in events)
    finishes = [record for record in events if record.event_kind == "ai.request_finish"]
    assert [(record.event_model, record.event_attempt, record.event_fallback, record.event_outcome)
            for record in finishes] == [("gemini-selected", 1, False, "provider_failure"),
                                       ("gemini-fallback", 2, True, "generated")]
    assert all(record.event_duration_seconds >= 0 for record in finishes)
    assert (finishes[-1].event_input_tokens, finishes[-1].event_output_tokens,
            finishes[-1].event_total_tokens) == (11, 7, 19)
    assert "PRIVATE" not in str([vars(record) for record in events])


@pytest.mark.asyncio
async def test_cancelled_attempt_and_fallback_failure_have_explicit_terminal_events(caplog):
    import asyncio
    import logging
    service = GeminiProvider(SimpleNamespace(gemini_model="first", gemini_fallback_model="second"))
    async def fail(model):
        raise ProviderError(404 if model == "first" else 500)
    with caplog.at_level(logging.INFO, logger="app.services.gemini_ai_service"):
        with pytest.raises(ProviderError):
            await service._request_with_model_fallback(fail, service.snapshot())
        async def cancel(_):
            raise asyncio.CancelledError()
        with pytest.raises(asyncio.CancelledError):
            await service._request_with_model_fallback(cancel, service.snapshot())
    finishes = [record for record in caplog.records if getattr(record, "event_kind", None) == "ai.request_finish"]
    assert [(record.event_model, record.event_outcome) for record in finishes] == [
        ("first", "provider_failure"), ("second", "provider_failure"), ("first", "cancelled")]


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
    service = SharedAIService(settings)

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
    service = GeminiProvider(settings)

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
    service = GeminiProvider(SimpleNamespace(gemini_api_key=SecretStr("key")))
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
