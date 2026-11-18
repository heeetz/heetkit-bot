from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import asyncio
import logging

import pytest

from app.command_settings import CommandNameConflict
from app.commands.leaderboard import register_leaderboard_commands
from app.commands.registry import CommandDispatcher, CommandRegistry
from app.config.settings import Settings
from app.database.database import Database
from app.database.repository import UserRepository
from app.leaderboards import Leaderboards, month_window
from app.runtime_state import RuntimeState
from app.services.twitch import TwitchAPIService
from app.twitch.client import TwitchChatBot
from app.twitch.events import ChatAuthor, IncomingChatMessage
from app.utils.cooldown import CooldownManager


def date(value):
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


@pytest.mark.parametrize("start,end", [
    ("2026-03-01T00:00:00", "2026-04-01T00:00:00"),
    ("2026-10-01T00:00:00", "2026-11-01T00:00:00"),
    ("2026-12-01T00:00:00", "2027-01-01T00:00:00"),
])
def test_month_starts_at_utc_midnight_across_dst_and_new_year(start, end):
    start, end = date(start), date(end)
    before = (end - timedelta(seconds=1)).astimezone(timezone(timedelta(hours=1)))
    assert month_window(before) == (start.strftime("%Y-%m"), start, end)
    assert month_window(end)[:2] == (end.strftime("%Y-%m"), end)


@pytest.fixture
async def setup():
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.initialize()
    now = SimpleNamespace(value=date("2026-11-10T00:00:00"))
    twitch = TwitchAPIService()
    users = UserRepository(database.session_factory)
    settings = SimpleNamespace(twitch_bot_user_id="999")
    board = twitch.leaderboards = Leaderboards(users, twitch, settings, clock=lambda: now.value)

    def connect(channel):
        client = object()
        twitch.bind(client, channel, settings.twitch_bot_user_id)
        twitch.set_chat_ready(client, True)
        return twitch.chat_session(client)

    async def record(user, name, *, at=None):
        channel, session = twitch.leaderboard_connection()
        message = IncomingChatMessage(channel, "hello", ChatAuthor(user, name), None, channel_id=channel,
                                      send_session=session, observed_at=at or now.value)
        await users.upsert_seen(user, name, seen_at=now.value, channel_id=channel, record_leaderboard=board.capture(message))

    try:
        yield board, users, now, connect, record
    finally:
        await board.close()
        await database.close()


async def test_channels_concurrent_counts_ties_rename_exclusion_and_privacy(setup):
    board, users, now, connect, record = setup
    connect("100")
    await asyncio.gather(*(record("1", "viewer") for _ in range(12)))
    for _ in range(12):
        await record("2", "other")
    await record("999", "sender")
    assert [(row["place"], row["messages"]) for row in await board.monthly("100", limit=10)] == [(1, 12), (1, 12)]
    await board.configure("100", [" @Viewer "])
    await record("1", "renamed")
    assert await board.monthly("100", user="1") == []
    await board.configure("100", [])
    assert await board.monthly("100", user="1") == [{"place": 1, "nickname": "renamed", "messages": 12}]
    connect("200")
    await record("1", "renamed")
    assert (await board.monthly("200", user="1"))[0]["messages"] == 1
    await users.opt_out("1", "renamed")
    await record("1", "renamed")
    assert await board.monthly("200", user="1") == []
    assert [row["nickname"] for row in await board.monthly("100", limit=10)] == ["other"]


async def test_broadcast_confirmation_gaps_reconnect_and_ended_stream(setup):
    board, users, now, connect, record = setup
    active = connect("100")
    first = SimpleNamespace(id="broadcast-1", started_at=now.value - timedelta(hours=1))
    await board._observe("100", active, first)
    now.value += timedelta(seconds=1)
    await record("1", "viewer")
    await record("2", "private")
    await users.opt_out("2", "private")
    assert (await board.snapshot("100"))["stream"]["rows"] == []
    await board._observe("100", active, first)
    assert (await board.snapshot("100"))["stream"]["rows"][0]["messages"] == 1
    now.value += timedelta(seconds=1)
    await record("1", "viewer")
    await board._observe("100", active, None, failed=True)
    assert (await board.snapshot("100"))["stream_status"] == "unknown"
    replacement = connect("100")
    second = SimpleNamespace(id="broadcast-2", started_at=now.value)
    await board._observe("100", active, second)  # Stale response from the retired session.
    await board._observe("100", replacement, first)
    assert (await board.snapshot("100"))["stream"]["rows"][0]["messages"] == 1
    await board._observe("100", replacement, None)
    await record("1", "viewer")  # Monthly only when offline.
    assert (await board.snapshot("100"))["stream"]["ends_at"]
    assert (await board.monthly("100", user="1"))[0]["messages"] == 3
    await board._observe("100", replacement, second)
    assert (await board.snapshot("100"))["stream"]["rows"] == []


async def test_utc_rollover_rejects_late_events(setup):
    board, _, now, connect, record = setup
    now.value = date("2026-03-31T23:59:50")
    connect("100")
    await record("1", "viewer")
    assert (await board.snapshot("100"))["month"]["period"] == "2026-03"
    old = now.value
    now.value = date("2026-04-01T00:00:00")
    await record("1", "viewer", at=old)
    result = (await board.snapshot("100"))["month"]
    assert result["started_at"] == "2026-04-01T00:00:00+00:00" and result["rows"] == []
    await record("1", "viewer")
    assert (await board.snapshot("100"))["month"]["period"] == "2026-04"


async def test_changing_sending_account_hides_its_existing_counts_and_stops_counting(setup):
    board, _, now, connect, record = setup
    active = connect("100")
    stream = SimpleNamespace(id="broadcast", started_at=now.value)
    await board._observe("100", active, stream)
    await record("777", "future_bot")
    await record("999", "old_bot")
    await record("111", "viewer")
    await board._observe("100", active, stream)
    assert await board.monthly("100", user="777")
    assert not await board.monthly("100", user="999")
    board.settings.twitch_bot_user_id = "777"
    active = connect("100")
    await board._observe("100", active, stream)
    await record("777", "renamed_bot")
    await record("999", "old_bot")
    await board._observe("100", active, stream)
    snapshot = await board.snapshot("100")
    for period in ("month", "stream"):
        assert {row["nickname"] for row in snapshot[period]["rows"]} == {"viewer", "old_bot"}
    assert (await board.monthly("100", user="999"))[0]["messages"] == 1
    assert await board.monthly("100", user="777") == []


async def test_explicit_exclusion_keeps_verified_id_when_sending_account_changes(setup):
    board, _, _, connect, record = setup
    connect("100")
    await board.configure("100", ["old_bot"])
    await record("999", "old_bot")
    board.settings.twitch_bot_user_id = "777"
    connect("100")
    await record("999", "renamed_old_bot")
    assert await board.monthly("100", user="999") == []
    await board.configure("100", [])
    await record("999", "renamed_old_bot")
    assert (await board.monthly("100", user="999"))[0]["messages"] == 1


async def test_rank_without_data_leaves_global_cooldown_available(setup, tmp_path):
    board, users, _, connect, record = setup
    connect("100")
    await record("1", "viewer")
    registry = CommandRegistry()
    register_leaderboard_commands(registry)
    path = tmp_path / "commands.json"
    state = RuntimeState(command_settings_path=path)
    state.configure_commands(registry.definitions())
    defaults = state.get_command_default_settings("top")
    with pytest.raises(CommandNameConflict, match="top"):
        state.save_command_settings("rank", primary_name="top", enabled=True,
                                    cooldown=defaults.cooldown, permission=defaults.permission)
    for size in (1, 3, 5, 10):
        state.save_command_settings("top", entry_limit=size, enabled=False,
                                    cooldown=defaults.cooldown, permission=defaults.permission)
        state.save_builtin_enabled("top", True)
        loaded = RuntimeState(command_settings_path=path)
        loaded.configure_commands(registry.definitions())
        assert loaded.get_command_settings("top").entry_limit == size
        assert loaded.get_command_settings("rank").entry_limit is None
    dispatcher = CommandDispatcher(registry, CooldownManager(), logging.getLogger("leaderboards-test"), "!", runtime_state=state)
    services = SimpleNamespace(users=users, twitch=board.twitch, runtime_state=state)
    responses = []

    async def reply(text):
        responses.append(text)
        return SimpleNamespace(sent=True)

    for user, name in (("2", "unknown"), ("1", "viewer")):
        await dispatcher.dispatch(IncomingChatMessage("100", "!rank", ChatAuthor(user, name), reply, channel_id="100"), services)
    assert responses == ["viewer, you’re #1 this month with 1 messages."]


async def test_restart_preserves_confirmed_counts_and_discards_the_open_interval(setup):
    board, users, now, connect, record = setup
    active = connect("100")
    stream = SimpleNamespace(id="broadcast", started_at=now.value)
    await board._observe("100", active, stream)
    now.value += timedelta(seconds=1)
    await record("1", "viewer")
    await board._observe("100", active, stream)
    now.value += timedelta(seconds=1)
    await record("1", "viewer")
    board.twitch.stop_chat()

    restarted = board.twitch.leaderboards = Leaderboards(users, board.twitch, board.settings, clock=lambda: now.value)
    await restarted.start()
    try:
        active = connect("100")
        await restarted._observe("100", active, stream)
        await restarted._observe("100", active, stream)
        result = await restarted.snapshot("100")
        assert result["stream"]["period"] == "broadcast" and result["stream"]["partial"]
        assert result["stream"]["rows"][0]["messages"] == 1
        assert result["month"]["rows"][0]["messages"] == 2
    finally:
        await restarted.close()


async def test_twitch_ingress_counts_shared_chat_without_sender_echoes_or_replays(setup):
    board, users, now, _, _ = setup
    settings = Settings(_env_file=None, twitch_client_id="synthetic", twitch_client_secret="synthetic",
                        twitch_bot_user_id="999", twitch_bot_username="sender",
                        twitch_channel_user_id="100", twitch_channel="channelname")
    registry = CommandRegistry()
    logger = logging.getLogger(__name__)
    dispatcher = CommandDispatcher(registry, CooldownManager(), logger, "!")
    services = SimpleNamespace(twitch=board.twitch, users=users, settings=settings, runtime_state=None,
                               filter_manager=SimpleNamespace(filter_message=lambda text: text != "filtered"))
    bot = TwitchChatBot(settings, settings.primary_account, services, dispatcher, logger)
    board.twitch.set_chat_ready(bot, True)

    async def send(text):
        return SimpleNamespace(id="correlated-output", sent=True)

    async def event(identifier, user, text="hello", source_id=None):
        raw = SimpleNamespace(id=identifier, source_id=source_id, text=text, respond=send, timestamp=now.value,
                              broadcaster=SimpleNamespace(id="100", name="channelname"),
                              chatter=SimpleNamespace(id=user, name=f"viewer{user}", subscriber=False, vip=False,
                                                      moderator=False, broadcaster=False))
        await bot.event_message(raw)

    try:
        await board.twitch.chat_messages.send("999", "100", send, "hello")
        await event("echo-copy", "999", source_id="correlated-output")
        await event("manual", "999")
        await asyncio.gather(event("shared-copy", "1", source_id="origin"), event("shared-copy", "1", source_id="origin"))
        await event("command", "1", "!unknown")
        await event("filtered", "1", "filtered")
        assert [(row["nickname"], row["messages"]) for row in await board.monthly("100", limit=10)] == [
            ("viewer1", 1),
        ]
    finally:
        await bot.close(save_tokens=False)
