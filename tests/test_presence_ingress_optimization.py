"""The chat ingress presence write can skip its unused returned row."""

import asyncio
import json
import logging

import pytest
from sqlalchemy import event, select
from sqlalchemy.dialects.sqlite import insert

from app.commands.diagnostics import command_trace, receipt_time
from app.database.database import Database
from app.database.models import LeaderboardCount, User
from app.database.repository import UserRepository


@pytest.mark.asyncio
async def test_upsert_seen_keeps_default_return_and_skips_final_presence_read(tmp_path):
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'profile.sqlite3'}")
    await database.initialize()
    users = UserRepository(database.session_factory)
    selects = []

    def observe_sql(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT") and "USERS" in statement.upper():
            selects.append(statement)

    event.listen(database.engine.sync_engine, "before_cursor_execute", observe_sql)
    try:
        created = await users.upsert_seen("42", "viewer", channel_id="100")
        assert created is not None and created.username == "viewer"
        assert len(selects) == 2  # Previous observation and the legacy returned row.

        selects.clear()
        result = await users.upsert_seen("43", "ingress", channel_id="100", return_user=False)
        assert result is None
        assert len(selects) == 1  # The previous observation still guards retention semantics.
    finally:
        event.remove(database.engine.sync_engine, "before_cursor_execute", observe_sql)

    stored = await users.get_by_twitch_user_id("43", channel_id="100")
    assert stored is not None and stored.username == "ingress"
    await database.close()


@pytest.mark.asyncio
async def test_skipped_return_preserves_counts_optout_and_file_backed_recovery(tmp_path):
    path = tmp_path / "profile.sqlite3"
    database = Database(f"sqlite+aiosqlite:///{path}")
    await database.initialize()
    users = UserRepository(database.session_factory)

    async def count_message(session):
        statement = insert(LeaderboardCount).values(
            channel_id="100", kind="month", period_id="2026-11",
            twitch_user_id="42", messages=1,
        )
        await session.execute(statement.on_conflict_do_update(
            index_elements=[LeaderboardCount.channel_id, LeaderboardCount.kind,
                            LeaderboardCount.period_id, LeaderboardCount.twitch_user_id],
            set_={"messages": LeaderboardCount.messages + 1},
        ))

    try:
        results = await asyncio.gather(*(users.upsert_seen(
                "42", "viewer", channel_id="100", record_leaderboard=count_message,
                return_user=False,
            ) for _ in range(20)))
        assert results == [None] * 20
        async with database.session_factory() as session:
            assert await session.scalar(select(LeaderboardCount.messages)) == 20

        await users.upsert_seen("43", "retained", channel_id="100", return_user=False)
        assert await users.opt_out("42", "viewer")
        assert await users.get_by_twitch_user_id("42", channel_id="100") is None
        async with database.session_factory() as session:
            assert await session.get(LeaderboardCount, ("100", "month", "2026-11", "42")) is None
        await database.close()

        reopened = Database(f"sqlite+aiosqlite:///{path}")
        await reopened.initialize()
        recovered_users = UserRepository(reopened.session_factory)
        try:
            retained = await recovered_users.get_by_twitch_user_id("43", channel_id="100")
            assert retained is not None and retained.username == "retained"
            assert await recovered_users.is_storage_opted_out("42")
            assert await recovered_users.get_by_twitch_user_id("42", channel_id="100") is None
            async with reopened.session_factory() as session:
                assert await session.get(LeaderboardCount, ("100", "month", "2026-11", "42")) is None
        finally:
            await reopened.close()
    finally:
        if database.engine is not None:
            await database.close()


@pytest.mark.asyncio
async def test_command_trace_records_presence_lock_wait(caplog):
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.initialize()
    users = UserRepository(database.session_factory)
    caplog.set_level(logging.INFO, logger="app.command_diagnostics")

    await users.policy.lock.acquire()
    try:
        with command_trace(receipt_time(), "weather", "synthetic-message-id", lambda: False):
            write = asyncio.create_task(users.upsert_seen(
                "42", "viewer", channel_id="100", return_user=False,
            ))
            for _ in range(100):
                waiters = getattr(users.policy.lock, "_waiters", None)
                if waiters and len(waiters) > 0:
                    break
                await asyncio.sleep(0.001)
            else:
                pytest.fail("presence write did not wait for the shared lock")
            await asyncio.sleep(0.01)
            users.policy.lock.release()
            await write
    finally:
        if users.policy.lock.locked():
            users.policy.lock.release()
    try:
        payload = next(
            json.loads(record.getMessage().removeprefix("Command trace "))
            for record in caplog.records
            if getattr(record, "event_kind", None) == "command.trace"
            and '"phase":"terminal"' in record.getMessage()
        )
        assert payload["db_wait_ms"] >= 10
    finally:
        await database.close()
