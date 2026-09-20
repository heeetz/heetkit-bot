"""Tests for the TwitchIO adapter without a Twitch network connection."""

import logging
from types import SimpleNamespace
from typing import cast

import pytest
from twitchio.exceptions import HTTPException, InvalidTokenException

from app.commands.registry import CommandDispatcher
from app.config.settings import Settings
from app.services.facade import ApplicationServices
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


class RecordingUsers:
    def __init__(self) -> None:
        self.seen_user_ids: list[str] = []

    async def record_seen(self, author) -> None:
        self.seen_user_ids.append(author.twitch_user_id)


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
async def test_twitch_message_maps_to_dto_persists_user_and_sends_response() -> None:
    raw_message = FakeTwitchMessage()
    mapped = to_incoming_chat_message(cast(object, raw_message))
    users = RecordingUsers()
    filter_manager = AllowingFilterManager()
    dispatcher = ReplyingDispatcher()
    services = cast(
        ApplicationServices,
        SimpleNamespace(users=users, filter_manager=filter_manager),
    )

    assert mapped.channel == "testchannel"
    assert mapped.author.is_subscriber is True
    assert mapped.author.is_moderator is True

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
