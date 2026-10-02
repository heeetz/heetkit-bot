"""Tests for the TwitchIO adapter without a Twitch network connection."""

import logging
from types import SimpleNamespace
from typing import cast

import pytest
from twitchio.exceptions import HTTPException, InvalidTokenException

from app.commands.registry import CommandDispatcher
from app.config.settings import Settings
from app.services.facade import ApplicationServices
from app.runtime_state import RuntimeState
from app.twitch.client import (
    TwitchChatBot,
    TwitchConnectionError,
    process_twitch_message,
    run_twitch_bot,
    to_incoming_chat_message,
)


class FakeTwitchMessage:
    def __init__(self, content: str = "!ping") -> None:
        self.broadcaster = SimpleNamespace(name="testchannel")
        self.chatter = SimpleNamespace(
            id="viewer-id",
            name="viewer",
            subscriber=True,
            vip=False,
            moderator=True,
            broadcaster=False,
        )
        self.text = content
        self.responses: list[str] = []

    async def respond(self, content: str) -> None:
        self.responses.append(content)


class RecordingUserRepository:
    def __init__(self) -> None:
        self.seen_user_ids: list[str] = []

    async def upsert_seen(self, *, twitch_user_id: str, username: str) -> None:
        self.seen_user_ids.append(twitch_user_id)


class AllowingFilterManager:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def filter_message(self, content: str) -> bool:
        self.messages.append(content)
        return True


class ReplyingDispatcher:
    def __init__(self) -> None:
        self.messages = []

    async def dispatch(self, message, services) -> bool:
        self.messages.append(message)
        await message.respond("pong")
        return True


def build_settings() -> Settings:
    return Settings(
        _env_file=None,
        twitch_client_id="client-id",
        twitch_client_secret="client-secret",
        twitch_bot_user_id="100",
        twitch_bot_username="testbot",
        twitch_channel_user_id="200",
        twitch_channel="testchannel",
    )


@pytest.mark.asyncio
async def test_twitch_message_maps_to_dto_persists_user_and_sends_response(
    caplog: pytest.LogCaptureFixture,
) -> None:
    raw_message = FakeTwitchMessage()
    mapped = to_incoming_chat_message(cast(object, raw_message))
    users = RecordingUserRepository()
    filter_manager = AllowingFilterManager()
    dispatcher = ReplyingDispatcher()
    services = cast(
        ApplicationServices,
        SimpleNamespace(users=users, filter_manager=filter_manager),
    )

    assert mapped.channel == "testchannel"
    assert mapped.author.is_subscriber is True
    assert mapped.author.is_moderator is True

    with caplog.at_level(logging.INFO, logger="tests.twitch"):
        await process_twitch_message(
            message=cast(object, raw_message),
            services=services,
            dispatcher=cast(CommandDispatcher, dispatcher),
            logger=logging.getLogger("tests.twitch"),
        )

    assert users.seen_user_ids == ["viewer-id"]
    assert filter_manager.messages == ["!ping"]
    assert dispatcher.messages[0].content == "!ping"
    assert raw_message.responses == ["pong"]
    incoming_record = next(
        record
        for record in caplog.records
        if getattr(record, "event_kind", None) == "chat.incoming"
    )
    assert incoming_record.event_username == "viewer"
    assert incoming_record.event_channel == "testchannel"


@pytest.mark.asyncio
async def test_run_twitch_bot_loads_and_saves_managed_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    class FakeBot:
        def __init__(self, **kwargs) -> None:
            calls.append(("init", (), kwargs))

        async def start(self, **kwargs) -> None:
            calls.append(("start", (), kwargs))

        async def close(self, **kwargs) -> None:
            calls.append(("close", (), kwargs))

    monkeypatch.setattr("app.twitch.client.TwitchChatBot", FakeBot)
    settings = build_settings()

    await run_twitch_bot(
        settings=settings,
        services=cast(ApplicationServices, object()),
        dispatcher=cast(CommandDispatcher, object()),
        logger=logging.getLogger("tests.twitch"),
    )

    assert calls[1] == (
        "start",
        (),
        {"with_adapter": True, "load_tokens": True, "save_tokens": True},
    )
    assert calls[2] == ("close", (), {"save_tokens": False})


@pytest.mark.asyncio
async def test_token_failure_is_logged_without_oauth_values(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class FakeBot:
        def __init__(self, **kwargs) -> None:
            return None

        async def start(self, **kwargs) -> None:
            original = HTTPException("sensitive request", status=400, extra={"message": "Invalid token"})
            raise InvalidTokenException("sensitive token", token="access-secret", refresh="refresh-secret", type_="token", original=original)

        async def close(self, **kwargs) -> None:
            return None

    monkeypatch.setattr("app.twitch.client.TwitchChatBot", FakeBot)

    with caplog.at_level(logging.ERROR), pytest.raises(TwitchConnectionError) as error:
        await run_twitch_bot(
            settings=build_settings(),
            services=cast(ApplicationServices, object()),
            dispatcher=cast(CommandDispatcher, object()),
            logger=logging.getLogger("tests.twitch"),
        )

    assert "Twitch user token validation failed status=400 invalid_type=token" in caplog.text
    assert "access-secret" not in caplog.text
    assert "refresh-secret" not in caplog.text
    assert str(error.value) == "Twitch user token validation failed."


@pytest.mark.asyncio
async def test_websocket_loss_and_welcome_update_connection_state(
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = build_settings()
    state = RuntimeState()
    state.set_bot_running(True)
    bot = TwitchChatBot(
        settings=settings,
        account=settings.primary_account,
        services=cast(ApplicationServices, SimpleNamespace(twitch=None, runtime_state=state)),
        dispatcher=cast(CommandDispatcher, object()),
        logger=logging.getLogger("tests.twitch.connection"),
    )
    bot._http._tokens["100"] = cast(object, {})

    with caplog.at_level(logging.INFO, logger="tests.twitch.connection"):
        await bot.event_websocket_welcome(SimpleNamespace(id="first"))
        await bot.event_ready()
        assert state.twitch_connection_state == "connected"

        await bot.event_websocket_closed(
            SimpleNamespace(socket=SimpleNamespace(session_id="first"))
        )
        assert state.twitch_connection_state == "reconnecting"
        assert state.twitch_connected is False

        await bot.event_websocket_welcome(SimpleNamespace(id="second"))
        assert state.twitch_connection_state == "connected"
        await bot.event_websocket_closed(
            SimpleNamespace(socket=SimpleNamespace(session_id="first"))
        )
        assert state.twitch_connection_state == "connected"

    assert [getattr(record, "event_kind", None) for record in caplog.records].count(
        "twitch.disconnected"
    ) == 1
    assert [getattr(record, "event_kind", None) for record in caplog.records].count(
        "twitch.recovered"
    ) == 1
    await bot.close(save_tokens=False)


@pytest.mark.asyncio
async def test_missing_oauth_and_terminal_auth_failure_are_distinct_from_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = build_settings()
    state = RuntimeState()
    state.set_bot_running(True)
    services = cast(ApplicationServices, SimpleNamespace(twitch=None, runtime_state=state))
    bot = TwitchChatBot(
        settings=settings,
        account=settings.primary_account,
        services=services,
        dispatcher=cast(CommandDispatcher, object()),
        logger=logging.getLogger("tests.twitch.auth"),
    )
    await bot.event_ready()
    assert state.twitch_connection_state == "auth_required"
    await bot.close(save_tokens=False)

    class FailingBot:
        async def start(self, **kwargs) -> None:
            original = HTTPException("private", status=401, extra={"message": "invalid"})
            raise InvalidTokenException("private", token="access-secret", refresh="refresh-secret", type_="token", original=original)

        async def close(self, **kwargs) -> None:
            return None

    monkeypatch.setattr("app.twitch.client.TwitchChatBot", lambda **kwargs: FailingBot())
    with pytest.raises(TwitchConnectionError):
        await run_twitch_bot(
            settings=settings,
            services=services,
            dispatcher=cast(CommandDispatcher, object()),
            logger=logging.getLogger("tests.twitch.auth"),
        )
    state.set_bot_running(False)
    assert state.twitch_connection_state == "auth_required"
    state.set_bot_running(True)
    assert state.twitch_connection_state == "connecting"


@pytest.mark.asyncio
async def test_terminal_configuration_failure_stops_in_failed_state(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    state = RuntimeState()
    state.set_bot_running(True)

    class FailingBot:
        async def start(self, **kwargs) -> None:
            raise HTTPException("private request detail", status=400)

        async def close(self, **kwargs) -> None:
            return None

    monkeypatch.setattr("app.twitch.client.TwitchChatBot", lambda **kwargs: FailingBot())
    with caplog.at_level(logging.ERROR), pytest.raises(TwitchConnectionError):
        await run_twitch_bot(
            settings=build_settings(),
            services=cast(ApplicationServices, SimpleNamespace(runtime_state=state)),
            dispatcher=cast(CommandDispatcher, object()),
            logger=logging.getLogger("tests.twitch.config"),
        )
    state.set_bot_running(False)
    assert state.twitch_connection_state == "failed"
    assert "private request detail" not in caplog.text
    assert any(getattr(record, "event_kind", None) == "twitch.failed" for record in caplog.records)


@pytest.mark.asyncio
async def test_revoked_chat_authorization_is_not_reported_as_reconnecting() -> None:
    settings = build_settings()
    state = RuntimeState()
    state.set_bot_running(True)
    bot = TwitchChatBot(
        settings=settings,
        account=settings.primary_account,
        services=cast(ApplicationServices, SimpleNamespace(twitch=None, runtime_state=state)),
        dispatcher=cast(CommandDispatcher, object()),
        logger=logging.getLogger("tests.twitch.revoked"),
    )
    bot._http._tokens["100"] = cast(object, {})
    await bot.event_websocket_welcome(SimpleNamespace(id="first"))
    await bot.event_ready()

    await bot.event_subscription_revoked(
        SimpleNamespace(
            type="channel.chat.message",
            status=SimpleNamespace(value="authorization_revoked"),
        )
    )
    await bot.event_websocket_closed(SimpleNamespace(socket=SimpleNamespace(session_id="first")))
    assert state.twitch_connection_state == "auth_required"
    await bot.close(save_tokens=False)


@pytest.mark.asyncio
async def test_oauth_callback_accepts_the_configured_bot_account(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = build_settings()
    bot = TwitchChatBot(
        settings=settings,
        account=settings.primary_account,
        services=cast(ApplicationServices, SimpleNamespace(twitch=None)),
        dispatcher=cast(CommandDispatcher, object()),
        logger=logging.getLogger("tests.twitch"),
    )
    calls: list[str] = []

    async def add_token(token: str, refresh: str) -> SimpleNamespace:
        calls.append("add")
        return SimpleNamespace(user_id="100")

    async def save_tokens() -> None:
        calls.append("save")

    async def subscribe() -> None:
        calls.append("subscribe")

    monkeypatch.setattr(bot, "add_token", add_token)
    monkeypatch.setattr(bot, "save_tokens", save_tokens)
    monkeypatch.setattr(bot, "_subscribe_to_chat", subscribe)

    await bot.event_oauth_authorized(
        {"access_token": "test-access", "refresh_token": "test-refresh", "user_id": "100"}
    )

    assert calls == ["add", "save", "subscribe"]
    await bot.close(save_tokens=False)


@pytest.mark.asyncio
async def test_oauth_callback_rejects_an_unexpected_account(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = build_settings()
    bot = TwitchChatBot(
        settings=settings,
        account=settings.primary_account,
        services=cast(ApplicationServices, SimpleNamespace(twitch=None)),
        dispatcher=cast(CommandDispatcher, object()),
        logger=logging.getLogger("tests.twitch"),
    )
    removed_users: list[str] = []

    async def add_token(token: str, refresh: str) -> SimpleNamespace:
        return SimpleNamespace(user_id="unexpected-user")

    async def remove_token(user_id: str) -> None:
        removed_users.append(user_id)

    monkeypatch.setattr(bot, "add_token", add_token)
    monkeypatch.setattr(bot, "remove_token", remove_token)

    await bot.event_oauth_authorized(
        {"access_token": "test-access", "refresh_token": "test-refresh", "user_id": "unexpected-user"}
    )

    assert removed_users == ["unexpected-user"]
    await bot.close(save_tokens=False)


@pytest.mark.asyncio
async def test_oauth_callback_discards_broadcaster_authorization(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = build_settings()
    bot = TwitchChatBot(
        settings=settings,
        account=settings.primary_account,
        services=cast(ApplicationServices, SimpleNamespace(twitch=None)),
        dispatcher=cast(CommandDispatcher, object()),
        logger=logging.getLogger("tests.twitch"),
    )
    removed_users: list[str] = []

    async def add_token(token: str, refresh: str) -> SimpleNamespace:
        return SimpleNamespace(user_id="200")

    async def remove_token(user_id: str) -> None:
        removed_users.append(user_id)

    monkeypatch.setattr(bot, "add_token", add_token)
    monkeypatch.setattr(bot, "remove_token", remove_token)

    await bot.event_oauth_authorized(
        {"access_token": "test-access", "refresh_token": "test-refresh", "user_id": "200"}
    )

    assert removed_users == ["200"]
    await bot.close(save_tokens=False)
