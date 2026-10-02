"""Tests for the shared application and Twitch session lifecycle."""

import asyncio
import logging
from types import SimpleNamespace
from typing import cast

import pytest

from app.bot_runtime import BotRuntime
from app.container import Application


class FakeRuntimeState:
    def __init__(self) -> None:
        self.running = False
        self.twitch_connection_state = "stopped"

    def set_bot_running(self, running: bool) -> None:
        self.running = running

    def set_twitch_connection_state(self, state: str) -> None:
        self.twitch_connection_state = state


class FakeApplication:
    def __init__(self) -> None:
        self.settings = SimpleNamespace(
            twitch_channel="oldchannel",
            twitch_channel_user_id="100",
        )
        self.dispatcher = object()
        self.services = SimpleNamespace(runtime_state=FakeRuntimeState())
        self.startup_calls = 0
        self.shutdown_calls = 0

    async def startup(self) -> None:
        self.startup_calls += 1

    async def shutdown(self) -> None:
        self.shutdown_calls += 1


@pytest.mark.asyncio
async def test_runtime_starts_and_stops_one_bot_session(monkeypatch) -> None:
    application = FakeApplication()
    bot_started = asyncio.Event()

    async def fake_run_twitch_bot(**kwargs) -> None:
        bot_started.set()
        await kwargs["stop_event"].wait()

    monkeypatch.setattr("app.bot_runtime.run_twitch_bot", fake_run_twitch_bot)
    runtime = BotRuntime(cast(Application, application), logging.getLogger("tests.runtime"))

    await runtime.startup()
    assert await runtime.start_bot() is True
    await bot_started.wait()
    assert application.services.runtime_state.running is True
    assert await runtime.start_bot() is False

    assert await runtime.stop_bot() is True
    assert application.services.runtime_state.running is False
    await runtime.shutdown()

    assert application.startup_calls == 1
    assert application.shutdown_calls == 1


@pytest.mark.asyncio
async def test_runtime_reconnects_running_session_with_new_channel(monkeypatch) -> None:
    application = FakeApplication()
    session_count = 0

    async def fake_run_twitch_bot(**kwargs) -> None:
        nonlocal session_count
        session_count += 1
        await kwargs["stop_event"].wait()

    monkeypatch.setattr("app.bot_runtime.run_twitch_bot", fake_run_twitch_bot)
    runtime = BotRuntime(cast(Application, application), logging.getLogger("tests.runtime"))
    await runtime.startup()
    await runtime.start_bot()
    await asyncio.sleep(0)

    assert await runtime.reconnect_twitch(
        channel="newchannel",
        channel_user_id="200",
    ) is True
    await asyncio.sleep(0)

    assert session_count == 2
    assert application.settings.twitch_channel == "newchannel"
    assert application.settings.twitch_channel_user_id == "200"
    assert application.services.runtime_state.running is True
    await runtime.shutdown()


@pytest.mark.asyncio
async def test_runtime_applies_twitch_settings_without_starting_stopped_bot(
    monkeypatch,
) -> None:
    application = FakeApplication()
    run_calls = 0

    async def fake_run_twitch_bot(**kwargs) -> None:
        nonlocal run_calls
        run_calls += 1

    monkeypatch.setattr("app.bot_runtime.run_twitch_bot", fake_run_twitch_bot)
    runtime = BotRuntime(cast(Application, application), logging.getLogger("tests.runtime"))
    await runtime.startup()

    assert await runtime.reconnect_twitch(
        channel="newchannel",
        channel_user_id="200",
    ) is False

    assert run_calls == 0
    assert application.settings.twitch_channel == "newchannel"
    assert application.settings.twitch_channel_user_id == "200"
    await runtime.shutdown()


@pytest.mark.asyncio
async def test_runtime_requires_application_startup() -> None:
    runtime = BotRuntime(
        cast(Application, FakeApplication()),
        logging.getLogger("tests.runtime"),
    )

    with pytest.raises(RuntimeError, match="startup"):
        await runtime.start_bot()


@pytest.mark.asyncio
async def test_stop_requested_during_startup_prevents_first_bot_session(monkeypatch) -> None:
    application = FakeApplication()
    run_calls = 0

    async def fake_run_twitch_bot(**kwargs) -> None:
        nonlocal run_calls
        run_calls += 1

    monkeypatch.setattr("app.bot_runtime.run_twitch_bot", fake_run_twitch_bot)
    runtime = BotRuntime(
        cast(Application, application),
        logging.getLogger("tests.runtime"),
    )

    runtime.request_stop()
    await runtime.startup()

    assert await runtime.start_bot() is False
    assert run_calls == 0
    await runtime.shutdown()


@pytest.mark.asyncio
async def test_failed_startup_still_releases_application_resources() -> None:
    application = FakeApplication()

    async def fail_startup() -> None:
        application.startup_calls += 1
        raise RuntimeError("database failed")

    application.startup = fail_startup
    runtime = BotRuntime(
        cast(Application, application),
        logging.getLogger("tests.runtime"),
    )

    with pytest.raises(RuntimeError, match="database failed"):
        await runtime.startup()
    await runtime.shutdown()

    assert application.shutdown_calls == 1
