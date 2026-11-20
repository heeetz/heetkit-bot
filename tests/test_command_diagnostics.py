import asyncio
import json
import logging
from dataclasses import replace
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.exc import OperationalError

from app.config.settings import Settings
from app.container import build_application
from app.database.models import utcnow
from app.headless import HeadlessLogFilter
from app.services.ai_provider import AIProviderCapabilities, AIProviderResponse, AIProviderSettings
from app.services.ai_service import SharedAIService
from app.services.contracts import WeatherReport
from app.services.weather import WeatherServiceError
from app.twitch.client import TwitchChatBot
from app.utils.cooldown import CooldownPolicy
from app.utils.logging import OperatorActivityHandler, RecentLogBuffer


TRACE_LOGGER = "app.command_diagnostics"


@pytest_asyncio.fixture
async def chat(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("HEETKIT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("HEETKIT_COMMAND_DIAGNOSTICS", "true")
    settings = Settings(_env_file=None, twitch_client_id="synthetic", twitch_client_secret="PRIVATE-CREDENTIAL",
                        twitch_bot_user_id="999", twitch_bot_username="syntheticbot",
                        twitch_channel_user_id="100", twitch_channel="syntheticchannel",
                        gemini_api_key=None, deepseek_api_key=None, openai_api_key=None)
    app = build_application(settings)
    provider = NS(name="synthetic", capabilities=AIProviderCapabilities(search=False), is_available=True,
                  snapshot=lambda: AIProviderSettings("synthetic", None),
                  generate=AsyncMock(return_value=AIProviderResponse("Synthetic answer.")), aclose=AsyncMock())
    ai = SharedAIService(settings, app.services.runtime_state, app.services.filter_manager, provider=provider)
    weather = AsyncMock(return_value=WeatherReport("City", 11, "clear", 7))
    services = app.services = replace(app.services, ai=ai, weather=NS(get_current_weather=weather))
    state = services.runtime_state
    state.set_ai_memory_enabled(False)
    for command in ("weather", "ask"):
        state.save_command_settings(command, enabled=True, cooldown=CooldownPolicy(),
                                    permission=state.get_command_default_settings(command).permission)
    services.twitch.output_limiter._interval = 0
    bot = TwitchChatBot(settings, settings.primary_account, services, app.dispatcher, logging.getLogger(__name__))

    async def fetch_streams(**kwargs):
        if False:
            yield

    monkeypatch.setattr(bot, "fetch_streams", fetch_streams)
    await app.startup()
    services.twitch.set_chat_ready(bot, True)
    caplog.set_level(logging.INFO, logger=TRACE_LOGGER)
    responder = AsyncMock(side_effect=lambda _: NS(id=str(uuid4()), sent=True))

    def message(content, *, user_id="123"):
        return NS(id=str(uuid4()), source_id=None, text=content, timestamp=utcnow(), respond=responder,
                  broadcaster=NS(id="100", name="syntheticchannel"),
                  chatter=NS(id=user_id, name="privateviewer", subscriber=False, vip=False,
                             moderator=False, broadcaster=False))

    def traces():
        records = [r for r in caplog.records if r.name == TRACE_LOGGER]
        assert all(HeadlessLogFilter().filter(record) for record in records)
        return [json.loads(r.getMessage().removeprefix("Command trace ")) for r in records]

    async def deliver(content, **kwargs):
        await bot.event_message(message(content, **kwargs))
        return traces()[-1]

    try:
        yield NS(bot=bot, services=services, state=state, provider=provider, weather=weather, message=message,
                 traces=traces, deliver=deliver, responder=responder)
    finally:
        await bot.close(save_tokens=False)
        await ai.aclose()
        await app.shutdown()


async def test_received_before_presence_wait_and_linked_to_confirmed_reply(chat):
    lock = chat.services.users.policy.lock
    incoming = chat.message("!weather PRIVATE-REQUEST")
    async with lock:
        task = asyncio.create_task(chat.bot.event_message(incoming))
        async with asyncio.timeout(2):
            while not lock._waiters:
                await asyncio.sleep(0.001)
        [received] = chat.traces()
        await asyncio.sleep(0.02)
    await task
    await chat.bot.event_message(incoming)
    received, terminal = chat.traces()
    assert received["phase"] == "received" and terminal["phase"] == "terminal"
    assert terminal["id"] == received["id"] and terminal["id"] != incoming.id
    assert terminal["received_utc"] == received["received_utc"]
    assert 15 <= terminal["db_wait_ms"] <= terminal["dispatch_ms"] <= terminal["handler_ms"]
    assert terminal["sends"] == {"attempted": 1, "confirmed": 1}
    assert terminal["reason"] == "confirmed_delivery"
    assert not any(value in str(chat.traces()) for value in
                   (incoming.id, "PRIVATE", "privateviewer", "syntheticchannel", "City"))
    chat.responder.assert_awaited_once()


@pytest.mark.parametrize(("mode", "reason", "ai_status", "sends"), [
    ("input", "filters", None, {}),
    ("user", "ai_user_blocked", None, {}),
    ("output", "filters", "output_blocked", {}),
    ("timeout", "provider_failure", "timeout", {}),
    ("provider_error", "provider_failure", "api_error", {}),
    ("limit", "output_limiter", "success", {"limited": 1}),
    ("failed", "delivery_failed", "success", {"attempted": 1, "rejected": 1}),
    ("uncertain", "uncertain_delivery", "success", {"attempted": 1, "uncertain": 1}),
    ("cooldown", "cooldown", None, {}),
])
async def test_ask_terminal_paths_through_twitch(chat, mode, reason, ai_status, sends):
    text = "!ask Give me an example"
    filters = chat.services.filter_manager
    if mode == "input":
        filters.add_blocked_word("example")
    elif mode == "user":
        chat.services.ai_user_blocks.block("privateviewer", "123")
    elif mode == "output":
        filters.add_blocked_word("answer")
    elif mode == "timeout":
        chat.provider.generate.side_effect = TimeoutError("PRIVATE-PROVIDER-ERROR")
    elif mode == "provider_error":
        chat.provider.generate.side_effect = RuntimeError("PRIVATE-PROVIDER-ERROR")
    elif mode == "limit":
        limiter = chat.services.twitch.output_limiter
        limiter._interval = 5
        assert limiter.try_acquire()
    elif mode in {"failed", "uncertain"}:
        chat.responder.side_effect = None
        chat.responder.return_value = NS(sent=False) if mode == "failed" else NS()
    elif mode == "cooldown":
        policy = chat.state.get_command_settings("ask")
        chat.state.save_command_settings("ask", enabled=True, cooldown=CooldownPolicy(global_seconds=60),
                                         permission=policy.permission)
        assert (await chat.deliver(text))["reason"] == "confirmed_delivery"
        chat.provider.generate.reset_mock()
    row = await chat.deliver(text)
    assert row["command"] == "ask"
    assert row["reason"] == reason and row["ai_status"] == ai_status and row["sends"] == sends
    assert ("PRIVATE" not in str(row) and "example" not in str(row))
    if mode in {"input", "user", "cooldown"}:
        assert row["handler_ms"] is None
        chat.provider.generate.assert_not_awaited()
    else:
        assert row["handler_ms"] is not None
        chat.provider.generate.assert_awaited_once()
    if mode == "input":
        assert row["input_block"] == "content_filter" and row["db_wait_ms"] is None


@pytest.mark.parametrize("mode", ["no_city", "timeout"])
async def test_weather_terminal_without_send(chat, mode):
    if mode == "no_city":
        chat.weather.return_value = None
    else:
        chat.weather.side_effect = WeatherServiceError("PRIVATE", reason="timeout")
    row = await chat.deliver("!weather PRIVATE-REQUEST")
    assert row["reason"] == ("city_not_found" if mode == "no_city" else "weather_timeout")
    assert row["handler_ms"] is not None and row["sends"] == {}
    chat.responder.assert_not_awaited()


async def test_presence_failure_is_separate_from_command_delivery(chat, monkeypatch):
    error = OperationalError("PRIVATE STATEMENT", {}, RuntimeError("PRIVATE DETAIL"))
    monkeypatch.setattr(chat.services.users, "upsert_seen", AsyncMock(side_effect=error))
    row = await chat.deliver("!weather PRIVATE-REQUEST")
    assert row["db_failed"] and row["reason"] == "confirmed_delivery"
    assert row["sends"] == {"attempted": 1, "confirmed": 1}
    assert "PRIVATE" not in str(row)


@pytest.mark.parametrize("stage", ["provider", "send"])
async def test_cancelled_ask_distinguishes_unattempted_from_uncertain_delivery(chat, stage):
    entered = asyncio.Event()

    async def blocked(*args):
        entered.set()
        await asyncio.Event().wait()

    (chat.provider.generate if stage == "provider" else chat.responder).side_effect = blocked
    task = asyncio.create_task(chat.bot.event_message(chat.message("!ask Give me an example")))
    async with asyncio.timeout(2):
        await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    row = chat.traces()[-1]
    assert row["cancelled"]
    if stage == "provider":
        assert row["outcome"] == "cancelled" and not row["sends"]
    else:
        assert row["outcome"] == "uncertain" and row["sends"] == {"attempted": 1, "uncertain": 1}


async def test_diagnostics_suppressed_for_optout_and_disabled_option(chat):
    buffer = RecentLogBuffer()
    handler = OperatorActivityHandler(buffer)
    logger = logging.getLogger()
    previous_level = logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    try:
        assert await chat.services.users.opt_out("123")
        await chat.bot.event_message(chat.message("!weather PRIVATE-REQUEST"))
        assert chat.traces() == [] and not buffer.recent_commands()
        chat.services.settings.heetkit_command_diagnostics = False
        await chat.bot.event_message(chat.message("!ask Give me an example", user_id="456"))
        assert chat.traces() == []
        assert chat.responder.await_count == 2
        [entry] = buffer.recent_commands()
        assert entry["context"]["invoked_name"] == "ask"
        assert entry["context"]["reason"] == "confirmed_delivery"
        assert entry["text"] is None and "username" not in entry["context"]
        assert entry in buffer.activity()["entries"]
        chat.services.filter_manager.add_blocked_word("answer")
        await chat.bot.event_message(chat.message("!ask Give me an example", user_id="456"))
        filtered, delivered = buffer.recent_commands()
        assert filtered["context"]["stage"] == "output_filter"
        assert filtered["context"]["outcome"] == "skipped"
        assert delivered == entry and chat.responder.await_count == 2
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)


async def test_optout_during_provider_wait_suppresses_terminal_trace(chat):
    entered, release = asyncio.Event(), asyncio.Event()

    async def provider(*args):
        entered.set()
        await release.wait()
        return AIProviderResponse("Synthetic answer.")

    chat.provider.generate.side_effect = provider
    task = asyncio.create_task(chat.bot.event_message(chat.message("!ask Give me an example")))
    try:
        async with asyncio.timeout(2):
            await entered.wait()
        assert [row["phase"] for row in chat.traces()] == ["received"]
        assert await chat.services.users.opt_out("123")
    finally:
        release.set()
        await task
    assert [row["phase"] for row in chat.traces()] == ["received"]
    chat.responder.assert_awaited_once()
