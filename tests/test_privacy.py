"""Retention and manual privacy requests use disposable synthetic databases only."""

import asyncio
from contextlib import closing
from datetime import timedelta
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock
import logging

import pytest
from sqlalchemy import select

from app.database.database import Database
from app.database.models import AIMemoryEntry, PrivacyOptOut, User, utcnow
from app.database.repository import AIMemoryRepository, UserRepository
from app.services.memory import AIMemoryService
from app.commands.ai import register_ai_commands
from app.commands.registry import CommandDispatcher, CommandRegistry
from app.runtime_state import RuntimeState
from app.services.ai_request_policy import AIRequestPolicy
from app.services.contracts import AIReply
from app.services.filter_manager import FilterManager
from app.twitch.client import process_twitch_message
from app.utils.cooldown import CooldownManager
from app.utils.logging import PrivacyLogFilter, RecentLogBuffer, RecentLogHandler, privacy_log_scope
from scripts.privacy_request import apply_request


async def stored(database, model):
    async with database.session_factory() as session:
        return list((await session.scalars(select(model))).all())


@pytest.mark.asyncio
async def test_history_retains_more_than_five_but_context_uses_last_five():
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.initialize()
    try:
        memory = AIMemoryService(AIMemoryRepository(database.session_factory))
        for index in range(8):
            await memory.save_exchange("123", f"question-{index}", f"reply-{index}", channel_id="100")
        await memory.save_exchange("456", "unaffected", "other reply", channel_id="100")
        assert len(await stored(database, AIMemoryEntry)) == 9
        entries = await memory.get_recent("123", channel_id="100")
        assert [entry.request_text for entry in entries] == [f"question-{index}" for index in range(3, 8)]
        assert "question-2" not in memory.format_context(entries)
        await memory.erase_for_user("123", channel_id="100")
        assert [entry.twitch_user_id for entry in await stored(database, AIMemoryEntry)] == ["456"]
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_retention_boundaries_inactive_users_and_unaffected_users():
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.initialize()
    try:
        now = utcnow()
        async with database.session_factory() as session:
            for user_id, days in (("expired", 60), ("active", 59), ("old", 61)):
                session.add(User(twitch_user_id=user_id, username=user_id, created_at=now - timedelta(days=200),
                                 last_seen_at=now - timedelta(days=days), channel_id="100"))
            for user_id, age in (("active", timedelta(days=60)), ("active", timedelta(days=60, microseconds=-1)),
                                 ("expired", timedelta(days=1)), ("old", timedelta(days=61))):
                session.add(AIMemoryEntry(twitch_user_id=user_id, request_text="synthetic", response_text="reply",
                                          created_at=now - age, channel_id="100"))
            session.add(PrivacyOptOut(twitch_user_id="999"))
            await session.commit()
        await database.cleanup_expired(now)
        assert [user.twitch_user_id for user in await stored(database, User)] == ["active"]
        entries = await stored(database, AIMemoryEntry)
        assert len(entries) == 2  # AI age is independent of presence inactivity.
        assert entries[0].created_at == now - timedelta(days=60, microseconds=-1)
        assert [item.twitch_user_id for item in await stored(database, PrivacyOptOut)] == ["999"]
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_expired_data_is_hidden_before_sweep_and_active_user_refresh_survives():
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.initialize()
    try:
        users = UserRepository(database.session_factory)
        memory = AIMemoryRepository(database.session_factory)
        await users.upsert_seen("123", "oldname", utcnow() - timedelta(days=181), channel_id="100")
        async with database.session_factory() as session:
            session.add(AIMemoryEntry(twitch_user_id="123", request_text="expired", response_text="reply",
                                      created_at=utcnow() - timedelta(days=91), channel_id="100"))
            await session.commit()
        assert await users.get_by_twitch_user_id("123", channel_id="100") is None
        assert await users.get_by_username("oldname", channel_id="100") is None
        assert await memory.get_recent("123", 5, channel_id="100") == []
        await users.upsert_seen("123", "renamed", channel_id="100")
        await database.cleanup_expired()
        assert (await users.get_by_username("renamed", channel_id="100")).twitch_user_id == "123"
    finally:
        await database.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["delete", "opt-out"])
async def test_manual_deletion_and_persistent_opt_out(tmp_path, action):
    path = tmp_path / "synthetic.db"
    database = Database("sqlite+aiosqlite:///" + str(path))
    await database.initialize()
    users = UserRepository(database.session_factory)
    memory = AIMemoryService(AIMemoryRepository(database.session_factory))
    for user_id in ("123", "456"):
        await users.upsert_seen(user_id, "viewer" + user_id, channel_id="100")
        await memory.save_exchange(user_id, "synthetic question", "synthetic reply", channel_id="100")
    await database.close()
    apply_request(path, "123", action)
    apply_request(path, "123", action)  # Repeated requests are safe.
    database = Database("sqlite+aiosqlite:///" + str(path))
    await database.initialize()
    try:
        users = UserRepository(database.session_factory)
        memory = AIMemoryService(AIMemoryRepository(database.session_factory))
        assert await users.get_by_twitch_user_id("123", channel_id="100") is None
        assert await memory.get_recent("123", channel_id="100") == []
        assert (await users.get_by_twitch_user_id("456", channel_id="100")).username == "viewer456"
        assert len(await memory.get_recent("456", channel_id="100")) == 1
        await users.upsert_seen("123", "renamed_account", channel_id="100")
        await memory.save_exchange("123", "late reply or new request", "reply", channel_id="100")
        if action == "opt-out":
            assert await stored(database, PrivacyOptOut)
            assert await users.get_by_twitch_user_id("123", channel_id="100") is None
            assert await memory.get_recent("123", channel_id="100") == []
            assert len(await stored(database, User)) == 1
            assert len(await stored(database, AIMemoryEntry)) == 1
        else:
            assert await users.get_by_twitch_user_id("123", channel_id="100") is not None
            assert len(await memory.get_recent("123", channel_id="100")) == 1
    finally:
        await database.close()
    if action == "opt-out":
        apply_request(path, "123", "delete")  # Deletion never removes suppression.
        apply_request(path, "123", "opt-in")
        database = Database("sqlite+aiosqlite:///" + str(path))
        await database.initialize()
        try:
            assert await stored(database, PrivacyOptOut) == []
            assert await UserRepository(database.session_factory).upsert_seen("123", "new_activity", channel_id="100") is not None
        finally:
            await database.close()


@pytest.mark.asyncio
async def test_existing_database_adds_suppression_table_and_cleans_at_startup(tmp_path):
    path = tmp_path / "old-synthetic.db"
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript("""
            CREATE TABLE users (id INTEGER PRIMARY KEY, twitch_user_id VARCHAR(32) UNIQUE,
                username VARCHAR(64), created_at DATETIME, last_seen_at DATETIME);
            CREATE TABLE ai_memory_entries (id INTEGER PRIMARY KEY, twitch_user_id VARCHAR(32),
                request_text VARCHAR(500), response_text VARCHAR(500), created_at DATETIME);
            INSERT INTO users VALUES (1, '123', 'expired', '2020-01-01', '2020-01-01');
            INSERT INTO ai_memory_entries VALUES (1, '123', 'synthetic', 'reply', '2020-01-01');
        """)
    (tmp_path / "legacy-channel-mapping.json").write_text('{"version":1,"channel_id":"100"}')
    database = Database("sqlite+aiosqlite:///" + str(path))
    await database.initialize()
    try:
        assert await stored(database, User) == []
        assert await stored(database, AIMemoryEntry) == []
        assert await stored(database, PrivacyOptOut) == []
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_periodic_cleanup_runs_without_chat_and_task_stops_on_close(monkeypatch):
    monkeypatch.setattr("app.database.database.RETENTION_CHECK_SECONDS", 0.01)
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.initialize()
    task = database._retention_task
    async with database.session_factory() as session:
        session.add(AIMemoryEntry(twitch_user_id="123", request_text="synthetic", response_text="reply",
                                  created_at=utcnow() - timedelta(days=91), channel_id="100"))
        await session.commit()
    try:
        async with asyncio.timeout(2):
            while await stored(database, AIMemoryEntry):
                await asyncio.sleep(0.01)
    finally:
        await database.close()
    assert task.done()
    assert database._retention_task is None


def test_manual_tool_refuses_missing_database_and_invalid_identity(tmp_path):
    path = tmp_path / "missing.db"
    with pytest.raises(sqlite3.OperationalError):
        apply_request(path, "123", "delete")
    assert not path.exists()
    for user_id in ("", "viewer", "１２３", "123; DELETE FROM users", "1" * 33):
        with pytest.raises(ValueError):
            apply_request(path, user_id, "opt-out")
    assert not path.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("memory_enabled,opted_out,delivered", [
    (False, False, True), (True, False, True), (True, True, True), (True, False, False),
    (True, False, None),
])
async def test_chat_storage_memory_off_opt_out_and_erase_remain_scoped(tmp_path, monkeypatch, memory_enabled, opted_out, delivered):
    monkeypatch.setenv("HEETKIT_DATA_DIR", str(tmp_path))
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.initialize()
    buffer = RecentLogBuffer()
    logger = logging.getLogger("tests.privacy.chat")
    handler = RecentLogHandler(buffer)
    logger.addHandler(handler)
    original_level = logger.level
    logger.setLevel(logging.INFO)
    try:
        users = UserRepository(database.session_factory)
        memory = AIMemoryService(AIMemoryRepository(database.session_factory))
        await users.upsert_seen("123", "viewer", channel_id="100")
        await users.upsert_seen("456", "unaffected", channel_id="100")
        await memory.save_exchange("123", "prior question", "prior answer", channel_id="100")
        await memory.save_exchange("456", "other question", "other answer", channel_id="100")
        if opted_out:
            async with database.session_factory() as session:
                session.add(PrivacyOptOut(twitch_user_id="123"))
                await session.commit()
            await database.cleanup_expired()
        state = RuntimeState()
        state.set_ai_memory_enabled(memory_enabled)
        ai = SimpleNamespace(is_available=True, generate_reply=AsyncMock(return_value=AIReply("Synthetic answer", True)))
        services = SimpleNamespace(users=users, memory=memory, runtime_state=state, ai=ai,
                                   ai_request_policy=AIRequestPolicy(), filter_manager=FilterManager())
        registry = CommandRegistry()
        register_ai_commands(registry)
        dispatcher = CommandDispatcher(registry, CooldownManager(), logger, "!")
        respond = AsyncMock(return_value=SimpleNamespace(sent=delivered))
        message = SimpleNamespace(text="!ask Explain photosynthesis", broadcaster=SimpleNamespace(name="channel", id="100"),
                                  chatter=SimpleNamespace(id="123", name="viewer", subscriber=False, vip=False,
                                                          moderator=False, broadcaster=False), respond=respond)
        await process_twitch_message(message, services, dispatcher, logger)
        respond.assert_awaited_once_with("@viewer Synthetic answer")
        context = ai.generate_reply.call_args.kwargs["memory_context"]
        if memory_enabled and not opted_out:
            assert "prior question" in context
        else:
            assert context is None
        expected_history = 0 if opted_out else 2 if memory_enabled and delivered else 1
        assert len(await memory.get_recent("123", channel_id="100")) == expected_history
        if opted_out:
            assert await users.get_by_twitch_user_id("123", channel_id="100") is None
            assert buffer.recent() == []
        else:
            assert buffer.recent()
        message.text = "!erase viewer"
        message.chatter.id = "999"
        message.chatter.name = "operator"
        await process_twitch_message(message, services, dispatcher, logger)
        assert len(await memory.get_recent("123", channel_id="100")) == expected_history
        message.chatter.broadcaster = True
        await process_twitch_message(message, services, dispatcher, logger)
        assert await memory.get_recent("123", channel_id="100") == []
        assert len(await memory.get_recent("456", channel_id="100")) == 1
        if not opted_out:
            assert await users.get_by_twitch_user_id("123", channel_id="100") is not None
    finally:
        logger.removeHandler(handler)
        logger.setLevel(original_level)
        await database.close()


@pytest.mark.asyncio
async def test_private_log_scope_does_not_hide_concurrent_viewer_or_later_logs():
    buffer = RecentLogBuffer()
    handler = RecentLogHandler(buffer)
    stream = []
    privacy_filter = PrivacyLogFilter()
    entered, release = asyncio.Event(), asyncio.Event()

    def emit(message):
        record = logging.LogRecord("synthetic", logging.INFO, __file__, 1, message, (), None)
        handler.emit(record)
        if privacy_filter.filter(record):
            stream.append(message)

    async def private_request():
        with privacy_log_scope(True):
            emit("private before")
            entered.set()
            await release.wait()
            emit("private after")

    task = asyncio.create_task(private_request())
    await entered.wait()
    emit("unaffected viewer")
    release.set()
    await task
    emit("later viewer")
    assert stream == ["unaffected viewer", "later viewer"]
    assert [entry["message"] for entry in buffer.recent()] == stream


@pytest.mark.asyncio
async def test_retention_failure_is_private_and_next_interval_recovers(monkeypatch, caplog):
    monkeypatch.setattr("app.database.database.RETENTION_CHECK_SECONDS", 0.01)
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.initialize()
    cleanup = database.cleanup_expired
    recovered = asyncio.Event()
    calls = 0

    async def flaky_cleanup():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("synthetic private bound value")
        await cleanup()
        recovered.set()

    monkeypatch.setattr(database, "cleanup_expired", flaky_cleanup)
    try:
        async with asyncio.timeout(2):
            await recovered.wait()
        assert "Privacy retention cleanup failed: RuntimeError" in caplog.text
        assert "synthetic private bound value" not in caplog.text
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_channel_membership_rename_expiry_and_independent_profile(tmp_path):
    databases = [Database("sqlite+aiosqlite:///" + str(tmp_path / profile / "synthetic.db")) for profile in ("one", "two")]
    for database in databases:
        await database.initialize()
    try:
        users = UserRepository(databases[0].session_factory)
        first_time = utcnow() - timedelta(days=2)
        original = await users.upsert_seen("123", "old_name", first_time, channel_id="100")
        renamed = await users.upsert_seen("123", "new_name", channel_id="100")
        other_channel = await users.upsert_seen("123", "other_name", channel_id="200")
        assert original.id == renamed.id and renamed.created_at == first_time
        assert other_channel.id != renamed.id
        assert await users.get_by_username("new_name", channel_id="200") is None
        assert await users.recent_usernames(channel_id="200") == ["other_name"]
        other_users = UserRepository(databases[1].session_factory)
        await other_users.upsert_seen("123", "independent", channel_id="100")
        await users.opt_out("123")
        assert await users.get_by_twitch_user_id("123", channel_id="100") is None
        assert await users.get_by_twitch_user_id("123", channel_id="200") is None
        assert (await other_users.get_by_twitch_user_id("123", channel_id="100")).username == "independent"
    finally:
        for database in databases:
            await database.close()


@pytest.mark.asyncio
async def test_nm_caps_are_enforced_on_writes_and_settings_for_each_scope(tmp_path):
    from app.app_settings import AppSettingsStore
    database = Database("sqlite+aiosqlite:///:memory:", history_limit=3, context_limit=2)
    await database.initialize()
    try:
        repository = AIMemoryRepository(database.session_factory)
        memory = AIMemoryService(repository)
        for channel in ("100", "200"):
            for viewer in ("123", "456"):
                for index in range(5):
                    await memory.save_exchange(viewer, f"question-{index}", "answer", channel_id=channel)
        assert len(await stored(database, AIMemoryEntry)) == 12
        assert [item.request_text for item in await memory.get_recent("123", channel_id="100")] == ["question-3", "question-4"]
        settings = AppSettingsStore(tmp_path / "app_settings.json")
        await database.configure_memory_limits(2, 1, persist=lambda: settings.update_ai_memory_limits(stored=2, context=1))
        assert len(await stored(database, AIMemoryEntry)) == 8
        assert len(await memory.get_recent("123", channel_id="100")) == 1
        assert AppSettingsStore(tmp_path / "app_settings.json").snapshot().ai.history_max_entries == 2
        async def late_write():
            await memory.save_exchange("123", "late question", "answer", channel_id="100")
        await asyncio.gather(late_write(), database.configure_memory_limits(1, 1))
        assert len(await stored(database, AIMemoryEntry)) == 4
        def failed_save():
            raise OSError("synthetic failed settings write")
        with pytest.raises(OSError):
            await database.configure_memory_limits(2, 1, persist=failed_save)
        assert repository.policy.stored == 1
    finally:
        await database.close()


@pytest.mark.parametrize("stored_count,context_count", [(0, 1), (501, 5), (2, 3), (10, 0), (100, 51), (True, 1), (10, "5")])
def test_nm_settings_validate_without_silent_expansion(tmp_path, stored_count, context_count):
    from app.app_settings import AppSettingsStore, load_app_settings
    from app.config.settings import Settings
    import json
    path = tmp_path / "app_settings.json"
    store = AppSettingsStore(path)
    with pytest.raises(ValueError):
        store.update_ai_memory_limits(stored=stored_count, context=context_count)
    assert not path.exists()
    path.write_text(json.dumps({"version": 1, "ai": {"history_max_entries": stored_count, "context_max_entries": context_count}}))
    with pytest.raises(ValueError, match="Invalid saved AI"):
        load_app_settings(path)
    with pytest.raises(ValueError):
        Settings(ai_history_max_entries=stored_count, ai_context_max_entries=context_count)


def twitch_message(text, user_id="123", channel_id="100"):
    return SimpleNamespace(text=text, id="synthetic-" + text, broadcaster=SimpleNamespace(id=channel_id, name="channel"),
        chatter=SimpleNamespace(id=user_id, name="viewer" + user_id, subscriber=False, vip=False, moderator=False, broadcaster=False),
        respond=AsyncMock(return_value=SimpleNamespace(sent=True)))


@pytest.mark.asyncio
@pytest.mark.parametrize("channel_id", ["", "nickname", "None", "1" * 33, 123])
async def test_storage_never_infers_channel_identity_from_a_nickname(channel_id):
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.initialize()
    try:
        await UserRepository(database.session_factory).upsert_seen("123", "viewer", channel_id=channel_id)
        await AIMemoryRepository(database.session_factory).append("123", "question", "answer", channel_id=channel_id)
        assert await stored(database, User) == []
        assert await stored(database, AIMemoryEntry) == []
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_optout_precedes_filters_bans_cooldowns_and_never_targets_arguments():
    from app.utils.logging import OperatorActivityHandler
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.initialize()
    try:
        users = UserRepository(database.session_factory)
        memory = AIMemoryService(AIMemoryRepository(database.session_factory))
        for viewer in ("123", "456"):
            for channel in ("100", "200"):
                await users.upsert_seen(viewer, "viewer" + viewer, channel_id=channel)
                await memory.save_exchange(viewer, "question", "answer", channel_id=channel)
        filters = SimpleNamespace(filter_message=lambda _: pytest.fail("Filter ran before opt-out"))
        services = SimpleNamespace(users=users, filter_manager=filters, settings=SimpleNamespace(command_prefix="?"), ai_user_blocks=object())
        dispatcher = SimpleNamespace(dispatch=AsyncMock(), is_ai_request_blocked=lambda *_: pytest.fail("Access policy ran before opt-out"))
        buffer = RecentLogBuffer()
        logger = logging.Logger("synthetic.optout", logging.INFO)
        logger.addHandler(OperatorActivityHandler(buffer))
        incoming = twitch_message("?optout 456", channel_id="200")
        await process_twitch_message(incoming, services, dispatcher, logger)
        await process_twitch_message(incoming, services, dispatcher, logger)  # Idempotent outside EventSub replay guard too.
        assert [row.twitch_user_id for row in await stored(database, PrivacyOptOut)] == ["123"]
        assert {row.twitch_user_id for row in await stored(database, User)} == {"456"}
        assert {row.twitch_user_id for row in await stored(database, AIMemoryEntry)} == {"456"}
        assert buffer.activity()["entries"] == []
        assert "provider" in incoming.respond.await_args.args[0]
        dispatcher.dispatch.assert_not_awaited()
    finally:
        await database.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("opt_out,withdraw", [(False, False), (True, False), (True, True)])
async def test_pending_ai_keeps_original_channel_and_optout_guards_late_logs_writes(opt_out, withdraw):
    from app.utils.logging import OperatorActivityHandler, operator_event
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.initialize()
    started, release = asyncio.Event(), asyncio.Event()
    users = UserRepository(database.session_factory)
    memory = AIMemoryService(AIMemoryRepository(database.session_factory))
    buffer = RecentLogBuffer()
    logger = logging.Logger("synthetic.pending", logging.INFO)
    logger.addHandler(OperatorActivityHandler(buffer))
    async def generate(**kwargs):
        started.set()
        await release.wait()
        operator_event(logger, "ai.request_finish", "generated")
        return AIReply("answer", True)
    settings = SimpleNamespace(command_prefix="!", twitch_channel_user_id="100")
    services = SimpleNamespace(users=users, memory=memory, ai=SimpleNamespace(is_available=True, generate_reply=generate),
        ai_request_policy=AIRequestPolicy(), filter_manager=FilterManager(), settings=settings)
    registry = CommandRegistry()
    register_ai_commands(registry)
    dispatcher = CommandDispatcher(registry, CooldownManager(), logger, "!")
    pending = asyncio.create_task(process_twitch_message(twitch_message("!ask question"), services, dispatcher, logger))
    try:
        await asyncio.wait_for(started.wait(), 2)
        settings.twitch_channel_user_id = "200"
        if opt_out:
            await process_twitch_message(twitch_message("!optout", channel_id="200"), services, dispatcher, logger)
            if withdraw:
                await users.withdraw_opt_out("123")
        previous_logs = buffer.activity()["entries"]
        release.set()
        await pending
        assert await memory.get_recent("123", channel_id="200") == []
        assert len(await memory.get_recent("123", channel_id="100")) == (0 if opt_out else 1)
        if opt_out:
            assert buffer.activity()["entries"] == previous_logs
            assert await stored(database, User) == []
            assert await stored(database, AIMemoryEntry) == []
        if opt_out and not withdraw:
            await users.upsert_seen("123", "renamed", channel_id="100")
            await memory.save_exchange("123", "late", "answer", channel_id="200")
            assert await stored(database, User) == []
            assert await stored(database, AIMemoryEntry) == []
    finally:
        release.set()
        await pending
        await database.close()
