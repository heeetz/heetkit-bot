"""Tests for the TwitchIO adapter without a Twitch network connection."""

import logging
import asyncio
from types import SimpleNamespace
from typing import cast
from urllib.parse import parse_qs, urlsplit
from unittest.mock import AsyncMock

import pytest
from twitchio.exceptions import HTTPException, InvalidTokenException

from app.commands.registry import CommandDispatcher
from app.config.settings import Settings, TwitchConfigurationError
from app.services.facade import ApplicationServices
from app.runtime_state import RuntimeState
from app.twitch.client import (
    CHAT_SCOPES,
    DesktopOAuthAdapter,
    OAUTH_STATE_TTL_SECONDS,
    OAUTH_REDIRECT_URI,
    TwitchChatBot,
    TwitchConnectionError,
    process_twitch_message,
    run_twitch_bot,
    to_incoming_chat_message,
)


def test_desktop_authorization_preserves_scopes_callback_and_consent(monkeypatch) -> None:
    adapter = DesktopOAuthAdapter(host="localhost", port=4343)
    calls = []

    def authorization_url(**kwargs):
        calls.append(kwargs)
        return {"url": "https://id.twitch.tv/oauth2/authorize?state=" + kwargs["state"]}

    adapter.client = SimpleNamespace(http=SimpleNamespace(get_authorization_url=authorization_url))
    first = adapter.begin_authorization()
    second = adapter.begin_authorization()
    assert first != second
    assert len(calls[0]["state"]) >= 32
    assert calls[0]["redirect_uri"] == OAUTH_REDIRECT_URI
    assert calls[0]["force_verify"] is True
    assert set(calls[0]["scopes"].selected) == {
        "user:read:chat", "user:write:chat", "user:bot", "moderator:read:followers",
        "moderator:manage:announcements",
    }


def oauth_adapter_probe(monkeypatch, clock=lambda: 0.0):
    from aiohttp import web

    adapter = DesktopOAuthAdapter(host="localhost", port=4343, clock=clock)
    adapter.client = SimpleNamespace(http=SimpleNamespace(
        get_authorization_url=lambda **kwargs: {"url": "https://id.twitch.tv/oauth2/authorize?state=" + kwargs["state"]},
    ))
    exchanges = []

    async def fetch_token(request):
        exchanges.append(request.query.get("code"))
        return SimpleNamespace(response=web.Response(status=200))

    monkeypatch.setattr(adapter, "fetch_token", fetch_token)
    return adapter, exchanges


def oauth_request(query):
    from aiohttp.test_utils import make_mocked_request

    return make_mocked_request("GET", "/oauth/callback?" + query, headers={"Host": "localhost:4343"})


@pytest.mark.asyncio
async def test_oauth_state_requires_desktop_initiation_and_is_single_use(monkeypatch) -> None:
    adapter, exchanges = oauth_adapter_probe(monkeypatch)
    assert (await adapter.oauth_redirect(oauth_request("scopes=user:read:chat"))).status == 403
    assert (await adapter.oauth_callback(oauth_request("code=synthetic&state=uninitiated"))).status == 400
    assert exchanges == []

    state = parse_qs(urlsplit(adapter.begin_authorization()).query)["state"][0]
    for query in ("code=synthetic", "code=synthetic&state=wrong", "code=synthetic&state=%C3%A9", f"code=synthetic&state={state}&state={state}"):
        assert (await adapter.oauth_callback(oauth_request(query))).status == 400
    assert exchanges == []
    request = oauth_request(f"code=synthetic&state={state}")
    assert (await adapter.oauth_callback(request)).status == 200
    assert (await adapter.oauth_callback(request)).status == 400
    assert exchanges == ["synthetic"]


@pytest.mark.asyncio
async def test_oauth_state_expires_and_cannot_cross_attempts_or_profiles(monkeypatch) -> None:
    now = 0.0
    adapter, exchanges = oauth_adapter_probe(monkeypatch, clock=lambda: now)
    other, _ = oauth_adapter_probe(monkeypatch)
    first = parse_qs(urlsplit(adapter.begin_authorization()).query)["state"][0]
    second = parse_qs(urlsplit(adapter.begin_authorization()).query)["state"][0]
    assert (await adapter.oauth_callback(oauth_request(f"code=synthetic&state={first}"))).status == 400
    other.begin_authorization()
    assert (await other.oauth_callback(oauth_request(f"code=synthetic&state={second}"))).status == 400
    now = OAUTH_STATE_TTL_SECONDS
    assert (await adapter.oauth_callback(oauth_request(f"code=synthetic&state={second}"))).status == 400
    assert exchanges == []


@pytest.mark.asyncio
async def test_oauth_state_is_consumed_before_exchange_yields_and_on_close(monkeypatch) -> None:
    import asyncio
    from aiohttp import web

    adapter, _ = oauth_adapter_probe(monkeypatch)
    state = parse_qs(urlsplit(adapter.begin_authorization()).query)["state"][0]
    entered, release = asyncio.Event(), asyncio.Event()

    async def fetch_token(request):
        entered.set()
        await release.wait()
        return SimpleNamespace(response=web.Response(status=200))

    monkeypatch.setattr(adapter, "fetch_token", fetch_token)
    request = oauth_request(f"code=synthetic&state={state}")
    task = asyncio.create_task(adapter.oauth_callback(request))
    await entered.wait()
    assert (await adapter.oauth_callback(request)).status == 400
    release.set()
    assert (await task).status == 200
    state = parse_qs(urlsplit(adapter.begin_authorization()).query)["state"][0]
    await adapter.close()
    assert (await adapter.oauth_callback(oauth_request(f"code=synthetic&state={state}"))).status == 400


@pytest.mark.asyncio
async def test_oauth_denial_consumes_state_without_exchanging_a_token(monkeypatch) -> None:
    adapter, exchanges = oauth_adapter_probe(monkeypatch)
    monkeypatch.setattr(adapter, "fetch_token", DesktopOAuthAdapter.fetch_token.__get__(adapter))
    state = parse_qs(urlsplit(adapter.begin_authorization()).query)["state"][0]
    assert (await adapter.oauth_callback(oauth_request(f"error=access_denied&state={state}"))).status == 400
    assert (await adapter.oauth_callback(oauth_request(f"code=synthetic&state={state}"))).status == 400
    assert exchanges == []


@pytest.mark.asyncio
async def test_bot_issues_state_for_running_initial_or_explicit_renewal_only() -> None:
    settings = build_settings()
    state = RuntimeState()
    bot = TwitchChatBot(
        settings=settings, account=settings.primary_account,
        services=cast(ApplicationServices, SimpleNamespace(twitch=None, runtime_state=state)),
        dispatcher=cast(CommandDispatcher, object()), logger=logging.getLogger("tests.twitch"),
    )
    try:
        with pytest.raises(ValueError, match="not currently required"):
            bot.begin_authorization()
        state.set_bot_running(True)
        state.set_twitch_connection_state("auth_required")
        url = urlsplit(bot.begin_authorization())
        assert url.scheme == "https" and url.netloc == "id.twitch.tv"
        assert parse_qs(url.query)["state"]
        state.set_twitch_connection_state("connected")
        assert parse_qs(urlsplit(bot.begin_authorization()).query)["state"]
        state.set_twitch_connection_state("reconnecting")
        with pytest.raises(ValueError, match="not currently required"):
            bot.begin_authorization()
    finally:
        await bot.close(save_tokens=False)
    state.set_twitch_connection_state("auth_required")
    with pytest.raises(ValueError, match="not currently required"):
        bot.begin_authorization()


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

    async def respond(self, content: str) -> object:
        self.responses.append(content)
        return SimpleNamespace(id=f"{getattr(self, 'id', 'request')}-response-{len(self.responses)}", sent=True)


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


@pytest.mark.asyncio
@pytest.mark.parametrize("opted_out,filtered", [(False, False), (True, False), (False, True), (True, True)])
async def test_activity_captures_commands_and_replies_but_not_ordinary_chat(opted_out, filtered):
    from app.commands.registry import CommandRegistry
    from app.utils.cooldown import CooldownManager, CooldownPolicy
    from app.utils.logging import RecentLogBuffer, OperatorActivityHandler
    users = RecordingUserRepository()
    users.is_storage_opted_out = AsyncMock(return_value=opted_out)
    services = SimpleNamespace(users=users, filter_manager=SimpleNamespace(filter_message=lambda text: not filtered))
    buffer = RecentLogBuffer()
    logger = logging.Logger("tests.activity", logging.INFO)
    logger.addHandler(OperatorActivityHandler(buffer))
    registry = CommandRegistry()
    @registry.command("ping", cooldown=CooldownPolicy(global_seconds=30))
    async def ping(context, arguments):
        await context.reply("@viewer Pong <literal>")
    dispatcher = CommandDispatcher(registry, CooldownManager(), logger, "!")
    for content in ("ordinary chat sentinel", "!ping", "!ping"):
        await process_twitch_message(FakeTwitchMessage(content), services, dispatcher, logger)
    entries = buffer.activity()["entries"]
    assert "ordinary chat sentinel" not in str(buffer.recent())
    if opted_out:
        assert entries == []
    elif filtered:
        assert len(entries) == 3
        assert all(entry["event_kind"] == "chat.filtered" and entry["text"] is None for entry in entries)
        assert all(set(entry["context"]) == {"event_id", "source", "outcome", "reason"} for entry in entries)
    else:
        assert users.seen_user_ids == ["viewer-id"] * 3
        assert [entry["text"] for entry in entries if entry["text"] is not None] == ["!ping", "@viewer Pong <literal>", "!ping"]
        cooldown = next(entry for entry in entries if entry["context"].get("outcome") == "cooldown")
        assert cooldown["context"]["retry_after_seconds"] > 0


@pytest.mark.asyncio
async def test_filter_diagnostic_stays_suppressed_when_privacy_lookup_fails():
    from app.commands.registry import CommandRegistry
    from app.utils.cooldown import CooldownManager
    from app.utils.logging import RecentLogBuffer, OperatorActivityHandler
    users = RecordingUserRepository()
    users.is_storage_opted_out = AsyncMock(side_effect=OSError("PRIVATE storage fault"))
    services = SimpleNamespace(users=users, filter_manager=SimpleNamespace(filter_message=lambda _: False))
    buffer = RecentLogBuffer()
    logger = logging.Logger("tests.filtered.privacy", logging.INFO)
    logger.addHandler(OperatorActivityHandler(buffer))
    dispatcher = CommandDispatcher(CommandRegistry(), CooldownManager(), logger, "!")
    await process_twitch_message(FakeTwitchMessage("!PRIVATE rejected text"), services, dispatcher, logger)
    assert buffer.activity()["entries"] == []
    assert users.seen_user_ids == []


@pytest.mark.asyncio
async def test_real_ingress_exposes_wait_and_quarantine_without_dispatching_dropped_input(tmp_path, caplog):
    from app.commands.fun import register_fun_commands
    from app.commands.registry import CommandRegistry
    from app.fun_settings import FunSettingsStore
    from app.services.twitch import TwitchAPIService
    from app.utils.cooldown import CooldownManager
    from app.utils.logging import RecentLogBuffer, OperatorActivityHandler
    caplog.set_level(logging.INFO)
    buffer = RecentLogBuffer()
    handler = OperatorActivityHandler(buffer)
    logging.getLogger().addHandler(handler)
    logger = logging.getLogger("tests.ingress.correlation")
    settings = build_settings()
    users = RecordingUserRepository()
    users.is_storage_opted_out = AsyncMock(return_value=False)
    services = SimpleNamespace(users=users, filter_manager=AllowingFilterManager(), settings=settings,
                               twitch=TwitchAPIService(), runtime_state=None)
    registry = CommandRegistry()
    register_fun_commands(registry, FunSettingsStore(tmp_path / "fun.json"))
    dispatcher = CommandDispatcher(registry, CooldownManager(), logger, "!",
                                   output_limiter=services.twitch.output_limiter)
    bot = TwitchChatBot(settings, settings.primary_account, services, dispatcher, logger)
    services.twitch.set_chat_ready(bot, True)
    entered, release = asyncio.Event(), asyncio.Event()
    async def lost(_):
        entered.set()
        await release.wait()
        raise OSError("PRIVATE lost result")
    first = FakeTwitchMessage("!tg")
    first.id, first.respond = "first", lost
    manual = FakeTwitchMessage("!tg")
    manual.id, manual.chatter.id = "manual", settings.twitch_bot_user_id
    control = FakeTwitchMessage("!tg")
    control.id = "control"
    task = waiting = None
    try:
        task = asyncio.create_task(bot.event_message(first))
        await entered.wait()
        waiting = asyncio.create_task(bot.event_message(manual))
        for _ in range(8):
            await asyncio.sleep(0)
        assert not waiting.done()
        await bot.event_message(control)
        assert len(control.responses) == 1
        release.set()
        await asyncio.gather(task, waiting)
        assert manual.responses == []
        assert settings.twitch_bot_user_id not in users.seen_user_ids
        entries = buffer.activity()["entries"]
        assert not any(e["event_kind"] == "command.input" and e["context"].get("input_message_id") == "manual" for e in entries)
        diagnostics = [e for e in entries if e["event_kind"] == "chat.correlation"]
        assert [e["context"]["outcome"] for e in diagnostics] == ["input_waiting", "input_paused", "input_dropped"]
        assert diagnostics[-1]["context"]["remaining_seconds"] > 590
        assert not any("username" in e["context"] or "input_message_id" in e["context"] for e in diagnostics)
        assert "PRIVATE" not in str(entries)
    finally:
        release.set()
        await asyncio.gather(*(t for t in (task, waiting) if t is not None), return_exceptions=True)
        await bot.close(save_tokens=False)
        logging.getLogger().removeHandler(handler)


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
@pytest.mark.parametrize("same_account", [False, True])
async def test_commands_response_echo_cannot_invoke_ask_or_consume_viewer_cooldown(same_account, caplog) -> None:
    from app.commands.ai import register_ai_commands
    from app.commands.info import register_info_commands
    from app.commands.registry import CommandRegistry
    from app.services.ai_request_policy import AIRequestPolicy
    from app.services.contracts import AIReply
    from app.utils.cooldown import CooldownManager

    settings = build_settings()
    caplog.set_level(logging.INFO, logger=__name__)
    registry = CommandRegistry()
    register_ai_commands(registry)
    register_info_commands(registry)
    state = RuntimeState()
    state.configure_commands(registry.definitions())
    generate = AsyncMock(return_value=AIReply(text="Viewer reply", is_available=True))
    services = SimpleNamespace(
        settings=settings, runtime_state=state, twitch=None,
        users=RecordingUserRepository(), filter_manager=AllowingFilterManager(),
        ai=SimpleNamespace(is_available=True, generate_reply=generate),
        ai_request_policy=AIRequestPolicy(),
    )
    dispatcher = CommandDispatcher(registry, CooldownManager(), logging.getLogger(__name__), "!", runtime_state=state)
    bot = TwitchChatBot(settings, settings.primary_account, services, dispatcher, logging.getLogger(__name__))
    request = FakeTwitchMessage("!commands")
    request.id = "viewer-commands"
    if same_account:
        request.chatter.id = settings.twitch_bot_user_id
        request.chatter.name = settings.twitch_bot_username
        request.chatter.broadcaster = True
    try:
        await bot.event_message(request)
        assert len(request.responses) == 1
        assert "!ask <question>" in request.responses[0]
        # Twitch EventSub delivers the sent message as a new event from the bot
        # account (which can also be the broadcaster), with a distinct chat ID.
        for index, content in enumerate((request.responses[0],)):
            echo = FakeTwitchMessage(content)
            echo.id = "viewer-commands-response-1"
            echo.chatter.id = settings.twitch_bot_user_id
            echo.chatter.name = settings.twitch_bot_username
            echo.chatter.broadcaster = True
            await bot.event_message(echo)
            assert echo.responses == []
        generate.assert_not_awaited()
        assert services.users.seen_user_ids == [request.chatter.id]

        question = FakeTwitchMessage("!ASK What is a telescope?")
        question.id = "viewer-question"
        if same_account:
            question.chatter = request.chatter
        await bot.event_message(question)
        await bot.event_message(question)  # replay must not double count input or sends
        generate.assert_awaited_once()
        assert generate.call_args.kwargs["prompt"] == "What is a telescope?"
        assert question.responses == [f"@{question.chatter.name} Viewer reply"]
        inputs = [record for record in caplog.records if getattr(record, "event_kind", None) == "command.input"]
        outputs = [record for record in caplog.records if getattr(record, "event_kind", None) == "chat.outgoing"]
        assert len(inputs) == len(outputs) == 2
        assert len({record.event_request_id for record in inputs}) == 2
        for incoming, outgoing in zip(inputs, outputs):
            assert incoming.event_request_id == outgoing.event_request_id
            assert outgoing.event_outcome == "confirmed_send"
            assert outgoing.event_message_id.startswith(incoming.event_input_message_id)
    finally:
        await bot.close(save_tokens=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ["!ask question", "!ping", "!custom", "ordinary reaction"])
async def test_manual_bot_account_messages_reach_filters_persistence_and_dispatch(content):
    settings = build_settings()
    raw = FakeTwitchMessage(content)
    raw.chatter.id = settings.twitch_bot_user_id
    raw.chatter.name = "changed-login"
    users = RecordingUserRepository()
    filters = AllowingFilterManager()
    dispatcher = ReplyingDispatcher()
    services = SimpleNamespace(settings=settings, users=users, filter_manager=filters)
    await process_twitch_message(raw, services, dispatcher, logging.getLogger(__name__))
    assert users.seen_user_ids == [settings.twitch_bot_user_id]
    assert filters.messages == [content]
    assert len(dispatcher.messages) == 1
    assert raw.responses == ["pong"]


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments,count", [("", 1), ("1", 1), ("5", 5), ("20", 20)])
async def test_duplicate_tg_delivery_does_not_start_a_second_burst(tmp_path, arguments, count) -> None:
    from app.commands.fun import register_fun_commands
    from app.commands.registry import CommandRegistry
    from app.fun_settings import FunSettingsStore
    from app.utils.cooldown import CooldownManager

    settings = build_settings()
    registry = CommandRegistry()
    register_fun_commands(registry, FunSettingsStore(tmp_path / "fun.json"))
    state = RuntimeState()
    state.configure_commands(registry.definitions())
    state.apply_command_settings("tg", burst_max_count=20)
    services = SimpleNamespace(twitch=None, users=RecordingUserRepository(),
                               filter_manager=AllowingFilterManager(), settings=settings)
    dispatcher = CommandDispatcher(registry, CooldownManager(), logging.getLogger(__name__), "!", runtime_state=state)
    bot = TwitchChatBot(settings, settings.primary_account, services, dispatcher, logging.getLogger(__name__))
    raw = FakeTwitchMessage(f"!tg {arguments}")
    raw.id = "same-chat-message"
    try:
        await asyncio.gather(bot.event_message(raw), bot.event_message(raw))
        await bot.event_message(raw)  # Replay after the first batch has finished.
        assert len(raw.responses) == count
        assert services.users.seen_user_ids == ["viewer-id"]
        raw.id = "different-chat-message"
        await bot.event_message(raw)  # Equal text with a new ID is a new invocation.
        assert len(raw.responses) == 2 * count
        assert services.users.seen_user_ids == ["viewer-id", "viewer-id"]
    finally:
        await bot.close(save_tokens=False)


@pytest.mark.asyncio
async def test_chat_delivery_cache_is_bounded_and_does_not_match_message_text(monkeypatch) -> None:
    settings = build_settings()
    services = SimpleNamespace(twitch=None, users=RecordingUserRepository(), filter_manager=AllowingFilterManager())
    dispatcher = ReplyingDispatcher()
    bot = TwitchChatBot(settings, settings.primary_account, services, dispatcher, logging.getLogger(__name__))
    bot._chat_messages.limit = 2
    try:
        for identifier in ("one", "two", "three", "three"):
            raw = FakeTwitchMessage()
            raw.id = identifier
            await bot.event_message(raw)
        assert [key[-1] for key in bot._chat_messages.seen] == ["two", "three"]
        assert len(dispatcher.messages) == 3
    finally:
        await bot.close(save_tokens=False)


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
    assert not any(getattr(record, "event_kind", None) == "chat.incoming" for record in caplog.records)
    assert "!ping" not in caplog.text


@pytest.mark.asyncio
async def test_direct_twitch_start_requires_credentials_before_creating_client(monkeypatch) -> None:
    settings = build_settings()
    settings.twitch_client_secret = None
    monkeypatch.setattr('app.twitch.client.TwitchChatBot', lambda **kwargs: pytest.fail('Client created'))
    with pytest.raises(TwitchConfigurationError, match='TWITCH_CLIENT_SECRET'):
        await run_twitch_bot(settings, cast(ApplicationServices, object()),
                             cast(CommandDispatcher, object()), logging.getLogger(__name__))


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
    caplog: pytest.LogCaptureFixture,
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
    assert "Authorize Twitch in HeetKit" in caplog.text
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
@pytest.mark.parametrize("renewal", [False, True])
async def test_oauth_callback_accepts_the_configured_bot_account(monkeypatch: pytest.MonkeyPatch, renewal) -> None:
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
    if renewal:
        bot._services.twitch = SimpleNamespace(chat_connected=True, set_chat_ready=lambda *args: None)

    await bot.event_oauth_authorized(
        {"access_token": "test-access", "refresh_token": "test-refresh", "user_id": "100"}
    )

    assert calls == (["add", "save"] if renewal else ["add", "save", "subscribe"])
    bot._services.twitch = None
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
