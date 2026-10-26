"""Task-5 saved choices and shared request routing use synthetic providers only."""

import asyncio
import logging
from dataclasses import asdict, replace
from unittest.mock import AsyncMock
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from app.app_settings import AppSettingsStore
from app.config.ai_setup import AIModelSelection, AISetup, parse_ai_setup
from app.config.personalities import SHARED_AI_INSTRUCTIONS
from app.config.profile_settings import apply_ai_app_settings
from app.config.settings import Settings
from app.services.ai_provider import AIProviderCapabilities, AIProviderResponse, AIProviderSettings, AISource
from app.services.ai_service import SharedAIService


def setup(**changes):
    return AISetup(AIModelSelection("deepseek", "deepseek-flash", "off"),
                   AIModelSelection("gemini", "gemini-2.5-flash", "off"),
                   cross_provider_acknowledged=True, **changes)


class Provider:
    capabilities = AIProviderCapabilities(search=True)
    is_available = True

    def __init__(self, name):
        self.name = name
        self.key = SecretStr(name + "-PRIVATE-KEY")
        self.generate = AsyncMock(return_value=AIProviderResponse("A friendly answer."))
        self.aclose = AsyncMock()

    def snapshot(self):
        return AIProviderSettings("unused", "unused-fallback", self.key)


def pipeline(configuration):
    service = SharedAIService(Settings(ai_provider=configuration.primary.provider, ai_setup=configuration))
    providers = {name: Provider(name) for name in ("deepseek", "gemini", "openai")}
    service._providers = providers
    return service, providers


def test_save_reload_empty_custom_reset_and_legacy_defaults(tmp_path):
    store = AppSettingsStore(tmp_path / "settings.json")
    legacy = apply_ai_app_settings(Settings(), store.snapshot())
    assert legacy.ai_setup is None
    custom = setup(shared_instructions="", max_question_length=2, max_answer_length=35,
                   provider_drafts={"primary:gemini": asdict(AIModelSelection("gemini", "manual-unknown"))})
    store.update_ai_setup(asdict(custom))
    reloaded = AppSettingsStore(store._path).snapshot()
    assert reloaded.ai.setup == custom
    assert apply_ai_app_settings(Settings(), reloaded).ai_provider == "deepseek"
    store.update_ai_setup(asdict(replace(custom, shared_instructions=None)))
    assert AppSettingsStore(store._path).snapshot().ai.setup.shared_instructions is None
    assert SHARED_AI_INSTRUCTIONS.startswith("You are a Twitch chat assistant.")


@pytest.mark.parametrize("patch", [
    {"max_question_length": 0}, {"max_answer_length": 451}, {"max_answer_length": True},
    {"cross_provider_acknowledged": False}, {"shared_instructions": "x" * 20001},
    {"primary": {"provider": "deepseek", "model": "manual-id", "thinking": "high", "search": False}},
    {"primary": {"provider": "deepseek", "model": "manual-id", "thinking": "default", "search": True}},
])
def test_invalid_setup_is_atomic(tmp_path, patch):
    store = AppSettingsStore(tmp_path / "settings.json")
    before = store.snapshot()
    with pytest.raises(ValueError):
        store.update_ai_setup({**asdict(setup()), **patch})
    assert store.snapshot() == before
    assert not store._path.exists()


def test_legacy_model_pair_updates_advanced_setup_without_losing_instructions(tmp_path):
    store = AppSettingsStore(tmp_path / "settings.json")
    store.update_ai_setup(asdict(setup(shared_instructions="Saved custom", max_answer_length=70)))
    updated = store.update_ai_models(provider="deepseek", selected_model="deepseek-v4-pro", fallback_model="deepseek-flash")
    assert updated.ai.setup.primary.model == "deepseek-v4-pro"
    assert updated.ai.setup.fallback.provider == "deepseek"
    assert updated.ai.setup.shared_instructions == "Saved custom" and updated.ai.setup.max_answer_length == 70
    with pytest.raises(ValueError):
        store.update_ai_models(provider="gemini")


async def test_cross_provider_single_fallback_snapshots_keys_options_and_instructions():
    service, providers = pipeline(setup(shared_instructions="Owner custom {literal} instructions", max_answer_length=30))
    captured = []

    async def primary(request, options):
        captured.append((request, options))
        providers["gemini"].key = SecretStr("ROTATED-KEY")
        service.settings.ai_setup = replace(service.settings.ai_setup, shared_instructions="Later settings")
        return AIProviderResponse(status="model_unavailable")

    providers["deepseek"].generate.side_effect = primary
    result = await service.generate_reply("hello", "viewer", "permitted history")
    assert result.is_available and len(result.text) <= 30
    request, options = providers["gemini"].generate.call_args.args
    assert options.api_key.get_secret_value() == "gemini-PRIVATE-KEY"
    assert options.thinking == "off" and options.single_attempt
    assert options.model == "gemini-2.5-flash"
    assert request.system_instruction == captured[0][0].system_instruction
    assert "Owner custom {literal} instructions" in request.system_instruction
    assert "Never:" not in request.system_instruction
    assert "permitted history" in request.content
    assert providers["deepseek"].generate.await_count == providers["gemini"].generate.await_count == 1


@pytest.mark.parametrize("status", ["api_error", "timeout", "configuration_error", "search_error", "provider_unavailable"])
async def test_only_model_unavailable_can_fallback(status):
    service, providers = pipeline(setup())
    providers["deepseek"].generate.return_value = AIProviderResponse(status=status)
    result = await service.generate_reply("hello", "viewer")
    assert result.status == status
    providers["gemini"].generate.assert_not_awaited()


async def test_missing_consent_allows_primary_but_never_routes():
    service, providers = pipeline(replace(setup(), cross_provider_acknowledged=False))
    assert (await service.generate_reply("hello", "viewer")).is_available
    providers["deepseek"].generate.return_value = AIProviderResponse(status="model_unavailable")
    assert (await service.generate_reply("hello", "viewer")).status == "configuration_error"
    providers["gemini"].generate.assert_not_awaited()


async def test_lengths_count_current_unicode_question_not_memory_and_reject_before_work():
    service, providers = pipeline(setup(max_question_length=2, max_answer_length=8))
    assert (await service.generate_reply("🙂🙂", "viewer", "history" * 1000)).is_available
    assert "at or below 8 characters" in providers["deepseek"].generate.call_args.args[0].system_instruction
    providers["deepseek"].generate.reset_mock()
    assert (await service.generate_reply("🙂🙂🙂", "viewer")).status == "question_too_long"
    providers["deepseek"].generate.assert_not_awaited()


async def test_search_off_mismatch_and_attribution_are_explicit():
    configuration = setup()
    service, providers = pipeline(configuration)
    assert (await service.generate_reply("latest weather", "viewer")).is_available
    assert not providers["deepseek"].generate.call_args.args[0].use_search
    service.settings.ai_setup = replace(configuration, primary=replace(configuration.primary, search=True))
    providers["deepseek"].generate.return_value = AIProviderResponse(status="model_unavailable")
    assert (await service.generate_reply("latest weather", "viewer")).status == "search_unavailable"
    providers["gemini"].generate.assert_not_awaited()
    providers["deepseek"].generate.return_value = AIProviderResponse("Fresh answer.", search_used=True,
        sources=(AISource("Source", "https://example.test/facts"),))
    reply = await service.generate_reply("latest weather", "viewer")
    assert reply.is_available and "https://example.test/facts" in reply.text and len(reply.text) <= 220
    providers["deepseek"].generate.return_value = AIProviderResponse("Fresh answer.", attribution_required=True)
    assert (await service.generate_reply("latest weather", "viewer")).status == "attribution_unavailable"

    service.settings.ai_setup = replace(service.settings.ai_setup, max_answer_length=20)
    providers["deepseek"].generate.return_value = AIProviderResponse("Fresh answer.", search_used=True,
        sources=(AISource("Source", "https://example.test/facts"),))
    assert (await service.generate_reply("latest weather", "viewer")).status == "attribution_unavailable"


async def test_citation_urls_remain_subject_to_profile_filters():
    from app.services.filter_manager import FilterManager
    configuration = setup()
    configuration = replace(configuration, primary=replace(configuration.primary, search=True))
    service, providers = pipeline(configuration)
    service.filter_manager = FilterManager()
    service.filter_manager.add_blocked_word("blockedsite")
    providers["deepseek"].generate.return_value = AIProviderResponse("Answer.", search_used=True,
        sources=(AISource("Source", "https://blockedsite.test/"),))
    result = await service.generate_reply("latest weather", "viewer")
    assert result.status == "output_blocked" and result.moderation_source == "editable_filter"


async def test_openai_preserves_inline_attribution_usage_and_exact_model_without_truncation():
    configuration = AISetup(AIModelSelection("openai", "gpt-6-luna", "none", True))
    service, providers = pipeline(configuration)
    text = "Fresh fact https://example.test/facts then a second claim https://example.test/other"
    providers["openai"].generate.return_value = AIProviderResponse(text, search_used=True,
        sources=(AISource("Fact", "https://example.test/facts"), AISource("Other", "https://example.test/other")),
        inline_citations=True, effective_model="gpt-6-luna", input_tokens=200, output_tokens=32)
    reply = await service.generate_reply("latest news", "viewer")
    assert reply.text == text and reply.generation.model == "gpt-6-luna"
    assert (reply.generation.input_tokens, reply.generation.output_tokens) == (200, 32)
    service.settings.ai_setup = replace(configuration, max_answer_length=len(text) - 1)
    withheld = await service.generate_reply("latest news", "viewer")
    assert withheld.status == "attribution_unavailable" and not withheld.text


async def test_openai_cross_provider_fallback_keeps_independent_options_and_consent():
    configuration = AISetup(AIModelSelection("openai", "gpt-6-luna", "none"),
                            AIModelSelection("deepseek", "deepseek-flash", "off"), True)
    service, providers = pipeline(configuration)
    providers["openai"].generate.return_value = AIProviderResponse(status="model_unavailable")
    reply = await service.generate_reply("hello", "viewer")
    assert reply.is_available and reply.generation.provider == "deepseek" and reply.generation.fallback_used
    assert providers["openai"].generate.call_args.args[1].thinking == "none"
    assert providers["deepseek"].generate.call_args.args[1].thinking == "off"
    service.settings.ai_setup = replace(configuration, cross_provider_acknowledged=False)
    providers["deepseek"].generate.reset_mock()
    assert (await service.generate_reply("hello", "viewer")).status == "configuration_error"
    providers["deepseek"].generate.assert_not_awaited()


def test_openai_setup_and_legacy_models_reload_without_changing_other_providers(tmp_path):
    store = AppSettingsStore(tmp_path / "settings.json")
    store.update_ai_models(provider="openai", selected_model="gpt-6-luna", fallback_model="gpt-6.1-sol")
    runtime = apply_ai_app_settings(Settings(), AppSettingsStore(store._path).snapshot())
    assert runtime.ai_provider == "openai" and runtime.openai_model == "gpt-6-luna"
    assert runtime.gemini_model == Settings().gemini_model
    value = AISetup(AIModelSelection("openai", "gpt-6-luna", "none", True),
                    provider_drafts={"primary:openai": asdict(AIModelSelection("openai", "gpt-6-luna", "low"))})
    store.update_ai_setup(asdict(value))
    assert AppSettingsStore(store._path).snapshot().ai.setup == value


async def test_one_total_deadline_and_cancellation(monkeypatch):
    import app.services.ai_service as module
    service, providers = pipeline(setup())
    async def wait(*args):
        await asyncio.sleep(1)
        return AIProviderResponse("Late")
    providers["deepseek"].generate.return_value = AIProviderResponse(status="model_unavailable")
    providers["gemini"].generate.side_effect = wait
    monkeypatch.setattr(module, "AI_REQUEST_TIMEOUT_SECONDS", .01)
    assert (await service.generate_reply("hello", "viewer")).status == "timeout"
    providers["deepseek"].generate.side_effect = asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await service.generate_reply("hello", "viewer")


async def test_discovery_rejects_results_after_key_rotation():
    service, providers = pipeline(setup())
    async def discover():
        providers["deepseek"].key = SecretStr("ROTATED")
        return ["deepseek-flash"]
    providers["deepseek"].discover_models = AsyncMock(side_effect=discover)
    from app.services.ai_provider import AIModelDiscoveryError
    with pytest.raises(AIModelDiscoveryError) as error:
        await service.discover_models("deepseek")
    assert error.value.code == "credentials_changed"


async def test_stale_model_options_are_explicit_and_do_no_provider_work():
    configuration = replace(setup(), primary=AIModelSelection("deepseek", "deepseek-manual", "high"))
    service, providers = pipeline(configuration)
    assert (await service.generate_reply("hello", "viewer")).status == "configuration_error"
    for provider in providers.values():
        provider.generate.assert_not_awaited()


async def test_same_provider_fallback_uses_its_own_effort_once():
    configuration = replace(setup(), fallback=AIModelSelection("deepseek", "deepseek-v4-pro", "high"))
    service, providers = pipeline(configuration)
    providers["deepseek"].generate.side_effect = [AIProviderResponse(status="model_unavailable"), AIProviderResponse("Answer.")]
    assert (await service.generate_reply("hello", "viewer")).is_available
    assert [call.args[1].thinking for call in providers["deepseek"].generate.call_args_list] == ["off", "high"]
    providers["gemini"].generate.assert_not_awaited()


async def test_real_adapter_fallback_diagnostics_keep_original_request(monkeypatch, caplog):
    from google import genai
    service = SharedAIService(Settings(ai_provider="deepseek", ai_setup=setup(),
        deepseek_api_key="PRIVATE-FIRST", gemini_api_key="PRIVATE-SECOND"))
    service._providers["deepseek"]._http_json = AsyncMock(return_value=(404, None))
    class Client:
        aio = SimpleNamespace(models=SimpleNamespace(generate_content=AsyncMock(
            return_value=SimpleNamespace(text="Answer.", candidates=[]))), aclose=AsyncMock())
        def close(self):
            pass
    monkeypatch.setattr(genai, "Client", lambda **kwargs: Client())
    try:
        with caplog.at_level(logging.INFO):
            assert (await service.generate_reply("hello", "viewer")).is_available
        starts = [record for record in caplog.records if getattr(record, "event_kind", None) == "ai.request_start"]
        assert len(starts) == 2
        assert all(record.event_requested_provider == "DeepSeek" for record in starts)
        assert all(record.event_requested_model == "deepseek-flash" for record in starts)
        assert [record.event_attempt for record in starts] == [1, 2]
        assert starts[-1].event_provider == "Google Gemini" and starts[-1].event_fallback
        assert "PRIVATE" not in caplog.text
    finally:
        await service.aclose()


async def test_legacy_deepseek_keeps_search_off_and_legacy_gemini_reports_its_actual_preference():
    from app.config.ai_setup import effective_ai_setup
    service = SharedAIService(Settings(ai_provider="deepseek", deepseek_api_key="synthetic"))
    transport = AsyncMock(return_value=(200, {"choices": [{"finish_reason": "stop", "message": {"content": "Answer."}}]}))
    service.provider._http_json = transport
    try:
        assert not effective_ai_setup(service.settings).primary.search
        assert (await service.generate_reply("latest weather", "viewer")).is_available
        assert "tools" not in transport.call_args.kwargs["json"]
        assert effective_ai_setup(Settings()).primary.search
        assert not effective_ai_setup(Settings(gemini_model="manual-unknown")).primary.search
    finally:
        await service.aclose()
