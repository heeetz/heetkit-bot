"""Synthetic aggregate accounting, privacy races and bounded off-loop storage."""

import asyncio
from datetime import datetime, timedelta, timezone
import logging
import sqlite3
import time
from types import SimpleNamespace as NS

import pytest
import pytest_asyncio

from app.analytics import Analytics, analytics_scope, analytics_scope_for, checked_analytics_scope_for
from app.analytics_pricing import estimate
from app.database.database import Database
from app.database.repository import UserRepository
from app.utils.logging import event_metadata, operator_event, privacy_log_scope


@pytest_asyncio.fixture
async def collector(tmp_path):
    current = [datetime(2026, 10, 30, 23, 59, 59, tzinfo=timezone.utc)]
    analytics = Analytics(tmp_path / "synthetic.analytics.sqlite3", clock=lambda: current[0])
    await analytics.start()
    analytics.test_time = current
    yield analytics
    await analytics.close()


async def rows(analytics, channel="200"):
    while analytics.queue:
        await analytics.flush()
    return (await analytics.snapshot(channel))["rows"]


def totals(records):
    result = {}
    for row in records:
        key = row["metric"]
        result[key] = result.get(key, 0) + row["value"]
    return result


@pytest.mark.asyncio
async def test_structured_events_are_independent_of_log_handlers_and_exclude_content(collector):
    logger = logging.getLogger("tests.aggregate.disabled")
    logger.disabled = True
    try:
        with analytics_scope(collector, "200"):
            operator_event(logger, "command.attempt", "known", command_id="ask", username="private_login", text="private prompt")
            operator_event(logger, "command.start", "executing", command_id="ask", request_id="private_request")
            operator_event(logger, "command.complete", "handler_completed", command_id="ask")
            operator_event(logger, "command.terminal", "skipped", command_id="ask", reason="permissions")
            operator_event(logger, "command.outcome", "unknown_command", command_id="unknown")
        records = await rows(collector)
        assert totals(records) == {"command.attempts": 1, "command.starts": 1, "command.skipped": 1}
        assert "private" not in str(records)
        assert not any(key in str(records) for key in ("username", "request_id", "prompt"))
    finally:
        logger.disabled = False


@pytest.mark.asyncio
async def test_fallback_attempts_and_unknown_tokens_do_not_become_command_errors(collector):
    with analytics_scope(collector, "200"):
        event_metadata("ai.logical_start")
        event_metadata("ai.request_start", provider="DeepSeek", model="synthetic")
        event_metadata("ai.request_finish", provider="DeepSeek", model="synthetic", outcome="provider_failure", input_tokens=5, duration_seconds=.3)
        event_metadata("ai.fallback", provider="DeepSeek", model="synthetic")
        event_metadata("ai.request_start", provider="OpenAI", model="gpt-4.1-mini")
        event_metadata("ai.request_finish", provider="OpenAI", model="gpt-4.1-mini", outcome="generated", input_tokens=100,
                       output_tokens=30, total_tokens=130, cached_input_tokens=80, reasoning_tokens=20, duration_seconds=1.1)
        event_metadata("ai.logical_finish", outcome="success")
    result = totals(await rows(collector))
    assert result["ai.requests"] == result["ai.completed"] == result["ai.errors"] == result["ai.successes"] == result["ai.fallbacks"] == 1
    assert result["ai.attempts"] == 2
    assert result["ai.input_tokens"] == 105 and result["ai.output_tokens"] == 30
    assert result["ai.usage_unknown"] == 1 and result["ai.price_missing"] == 1
    assert result["ai.estimated_usd"] == pytest.approx(.000064)
    assert result["ai.latency_le_0_5"] == result["ai.latency_le_2"] == 1
    assert "command.error" not in result


@pytest.mark.asyncio
async def test_playground_separate_and_optout_failure_suppresses_events(collector):
    with analytics_scope(collector, "playground"):
        event_metadata("ai.logical_start")
    with analytics_scope(collector, "200"), privacy_log_scope(True):
        event_metadata("ai.logical_start")
    assert totals(await rows(collector, "playground")) == {"ai.requests": 1}
    assert await rows(collector) == []


@pytest.mark.asyncio
async def test_optout_revokes_queued_and_late_events_even_after_withdrawal(collector, tmp_path):
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'personal.sqlite3'}")
    await database.initialize()
    users = UserRepository(database.session_factory)
    users.analytics = collector
    message = NS(author=NS(twitch_user_id="300"), channel_id="200")
    try:
        with users.storage_scope("300"), analytics_scope_for(NS(analytics=collector, users=users), message):
            event_metadata("ai.logical_start")
            await users.opt_out("300")
            await users.withdraw_opt_out("300")
            event_metadata("ai.logical_finish", outcome="success")
        assert await rows(collector) == []
        with analytics_scope_for(NS(analytics=collector, users=users), message):
            event_metadata("ai.logical_start")
        assert totals(await rows(collector)) == {"ai.requests": 1}
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_direct_dispatch_scope_honors_existing_suppression_and_check_failure(collector, tmp_path):
    from unittest.mock import AsyncMock
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'personal.sqlite3'}")
    await database.initialize()
    users = UserRepository(database.session_factory)
    message = NS(author=NS(twitch_user_id="300"), channel_id="200")
    try:
        await users.opt_out("300")
        fresh_users = UserRepository(database.session_factory)
        services = NS(analytics=collector, users=fresh_users)
        with await checked_analytics_scope_for(services, message):
            event_metadata("ai.logical_start")
        services.users = NS(is_storage_opted_out=AsyncMock(side_effect=OSError))
        with await checked_analytics_scope_for(services, message):
            event_metadata("ai.logical_start")
        assert await rows(collector) == []
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_optout_waits_for_inflight_batch_and_revokes_its_contribution(collector, tmp_path, monkeypatch):
    from threading import Event
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'personal.sqlite3'}")
    await database.initialize()
    users = UserRepository(database.session_factory)
    users.analytics = collector
    entered, release = Event(), Event()
    original_write = collector._write
    def delayed_write(batch):
        entered.set()
        assert release.wait(3)
        original_write(batch)
    monkeypatch.setattr(collector, "_write", delayed_write)
    message = NS(author=NS(twitch_user_id="300"), channel_id="200")
    try:
        with analytics_scope_for(NS(analytics=collector, users=users), message):
            event_metadata("ai.logical_start")
        flush = asyncio.create_task(collector.flush())
        assert await asyncio.to_thread(entered.wait, 3)
        optout = asyncio.create_task(users.opt_out("300"))
        await asyncio.sleep(0)
        assert users.policy.privacy_epochs["300"] == 1 and not optout.done()
        release.set()
        await asyncio.wait_for(asyncio.gather(flush, optout), 3)
        assert await rows(collector) == []
    finally:
        release.set()
        await database.close()


@pytest.mark.asyncio
async def test_collector_observer_failure_cannot_break_command_events(collector, monkeypatch):
    monkeypatch.setattr(collector, "observe", lambda *args, **kwargs: (_ for _ in ()).throw(OSError()))
    with analytics_scope(collector, "200"):
        event_metadata("command.attempt", command_id="ping")
    assert collector.dropped == 1


@pytest.mark.asyncio
async def test_cancelled_flush_keeps_barrier_until_real_writer_exits(collector, monkeypatch):
    from threading import Event
    entered, release = Event(), Event()
    original_write = collector._write
    def delayed_write(batch):
        entered.set()
        assert release.wait(3)
        original_write(batch)
    monkeypatch.setattr(collector, "_write", delayed_write)
    collector.record("activity.observed", channel_id="200")
    flush = asyncio.create_task(collector.flush())
    assert await asyncio.to_thread(entered.wait, 3)
    flush.cancel()
    barrier = asyncio.create_task(collector.privacy_barrier())
    await asyncio.sleep(0)
    assert not barrier.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await flush
    await asyncio.wait_for(barrier, 3)
    assert totals(await rows(collector)) == {"activity.observed": 1}


@pytest.mark.asyncio
async def test_disable_reset_clear_pending_and_invalidate_late_scopes(collector):
    with analytics_scope(collector, "200"):
        event_metadata("ai.logical_start")
        await collector.reset()
        event_metadata("ai.logical_finish", outcome="success")
    assert await rows(collector) == []
    await collector.configure(False)
    collector.record("activity.observed", channel_id="200")
    assert not collector.queue
    with analytics_scope(collector, "200"):
        await collector.configure(True)
        event_metadata("ai.logical_start")
    assert await rows(collector) == []
    con = sqlite3.connect(collector.path)
    assert dict(con.execute("SELECT key,value FROM metadata"))["enabled"] == "1"
    con.close()


@pytest.mark.asyncio
async def test_midnight_retention_and_connection_time_split(collector):
    collector.connection("200", True)
    collector.test_time[0] += timedelta(seconds=2)
    collector.connection("200", False)
    collector.connection("200", True)
    records = await rows(collector)
    duration = {r["day"]: r["value"] for r in records if r["metric"] == "connection.seconds"}
    assert duration == {"2026-10-30": 1, "2026-10-31": 1}
    assert totals(records)["connection.reconnects"] == 1
    collector.record("activity.observed", channel_id="200", at=collector.clock() - timedelta(days=59))
    collector.record("activity.observed", channel_id="200", at=collector.clock() - timedelta(days=60))
    records = await rows(collector)
    assert totals(records)["activity.observed"] == 1
    collector.test_time[0] += timedelta(days=60)
    assert (await collector.snapshot("200"))["rows"] == []
    await collector.flush()
    con = sqlite3.connect(collector.path)
    assert con.execute("SELECT COUNT(*) FROM daily").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM hourly").fetchone()[0] == 0
    con.close()


@pytest.mark.asyncio
async def test_writer_lock_failure_drops_visible_batch_and_recovers_without_replay(collector):
    con = sqlite3.connect(collector.path)
    con.execute("BEGIN IMMEDIATE")
    collector.record("activity.observed", channel_id="200")
    await collector.flush()
    assert collector.write_failures == collector.dropped == 1 and not collector.available
    con.rollback()
    con.close()
    collector.record("activity.observed", channel_id="200")
    assert totals(await rows(collector)) == {"activity.observed": 1}
    assert collector.available


@pytest.mark.asyncio
async def test_bounded_busy_chat_and_query_plans(collector):
    latencies = []
    start = time.perf_counter()
    with analytics_scope(collector, "200"):
        for index in range(10_000):
            before = time.perf_counter()
            event_metadata("activity.observed")
            if index % 10 == 0:
                event_metadata("command.attempt", command_id="ping")
                event_metadata("command.terminal", command_id="ping", outcome="success")
            latencies.append(time.perf_counter() - before)
            if index % 128 == 0:
                await collector.flush()
    assert len(collector.queue) <= collector.capacity
    records = await rows(collector)
    assert collector.dropped == 0
    assert totals(records)["activity.observed"] == 10000
    assert totals(records)["command.attempts"] == totals(records)["command.success"] == 1000
    p99 = sorted(latencies)[int(len(latencies) * .99)]
    print(f"synthetic 10000-input workload: wall={time.perf_counter()-start:.3f}s record-p99={p99*1000:.3f}ms writer={collector.write_seconds:.3f}s lock-wait={collector.lock_wait_seconds:.6f}s drops={collector.dropped}")
    assert p99 < .1  # detects accidental SQLite/lock waits on ingress; no microbenchmark gate.
    con = sqlite3.connect(collector.path)
    read_plan = str(con.execute("EXPLAIN QUERY PLAN SELECT * FROM daily WHERE channel=? AND day>=?", ("200", "2026-10-01")).fetchall())
    expiry_plan = str(con.execute("EXPLAIN QUERY PLAN DELETE FROM daily WHERE day<?", ("2026-09-01",)).fetchall())
    assert "PRIMARY KEY" in read_plan and "daily_expiry" in expiry_plan
    con.close()


@pytest.mark.asyncio
async def test_overload_is_bounded_and_drops_are_persisted(collector):
    for _ in range(collector.capacity + 10):
        collector.record("activity.observed", channel_id="200")
    assert len(collector.queue) == collector.capacity and collector.dropped == 10
    await rows(collector)
    assert (await collector.snapshot("200"))["metadata"]["dropped"] == "10"


@pytest.mark.asyncio
async def test_dimensions_and_channels_stay_bounded(collector):
    for index in range(300):
        collector.record("command.attempts", channel_id="200", dimension=f"custom:{index}")
    await rows(collector)
    for index in range(1000, 1040):
        collector.record("activity.observed", channel_id=str(index))
    await rows(collector)
    con = sqlite3.connect(collector.path)
    assert con.execute("SELECT COUNT(DISTINCT dimension) FROM daily WHERE channel='200'").fetchone()[0] <= 257
    assert con.execute("SELECT COUNT(DISTINCT channel) FROM daily").fetchone()[0] <= 32
    con.close()


@pytest.mark.asyncio
async def test_current_retained_users_excludes_expired_suppressed_and_other_channels(tmp_path):
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'personal.sqlite3'}")
    await database.initialize()
    users = UserRepository(database.session_factory)
    try:
        await users.upsert_seen("1", "synthetic", channel_id="200")
        await users.upsert_seen("2", "synthetic", channel_id="201")
        await users.upsert_seen("3", "synthetic", channel_id="200", seen_at=datetime.now(timezone.utc) - timedelta(days=61))
        await users.upsert_seen("4", "synthetic", channel_id="200")
        await users.opt_out("4")
        assert await users.retained_count(channel_id="200") == 1
    finally:
        await database.close()


def test_pricing_unknowns_dates_cache_and_reasoning_subsets():
    now = datetime(2026, 10, 30, tzinfo=timezone.utc)
    usage = {"input_tokens": 100, "output_tokens": 30, "cached_input_tokens": 80, "reasoning_tokens": 20}
    assert estimate("openai", "gpt-4.1-mini", usage, now) == (pytest.approx(.000064), False)
    assert estimate("deepseek", "unpriced", usage, now) == (None, True)
    assert estimate("openai", "gpt-4.1-mini", usage, now - timedelta(days=1)) == (None, True)
    assert estimate("openai", "gpt-4.1-mini", {"output_tokens": 30}, now) == (pytest.approx(.000048), True)
    assert estimate("openai", "gpt-4.1-mini", {**usage, "search_requests": 1}, now)[1]
    assert estimate("openai", "gpt-4.1-mini", {**usage, "search_requests": 1}, now)[0] == pytest.approx(.010064)


@pytest.mark.asyncio
async def test_hourly_observations_and_coverage_split_at_utc_hours_and_midnight(collector):
    collector.test_time[0] = datetime(2026, 10, 30, 23, 59, 59, tzinfo=timezone.utc)
    collector.connection("200", True)
    collector.record("command.attempts", channel_id="200", dimension="ask")
    collector.test_time[0] += timedelta(seconds=2)
    collector.connection("200", False)
    collector.record("command.attempts", channel_id="200", dimension="ask", value=2)
    collector._checkpoint_coverage()
    await rows(collector)
    today = await collector.snapshot("200", 1)
    assert today["resolution"] == "hour"
    assert totals(today["rows"])["command.attempts"] == 2
    assert totals(today["hourly_rows"])["command.attempts"] == 2
    assert {row["day"] for row in today["hourly_rows"]} == {"2026-10-31T00:00:00+00:00"}
    assert totals(today["hourly_rows"])["connection.seconds"] == 1
    profile = await collector.snapshot("profile", 1)
    assert totals(profile["hourly_rows"]) == {"coverage.seconds": 1, "users.coverage_seconds": 1}
    weekly = await collector.snapshot("200", 7)
    assert weekly["resolution"] == "day" and weekly["hourly_rows"] == []
    assert totals(weekly["rows"])["command.attempts"] == 3
    assert totals(weekly["rows"])["connection.seconds"] == 2
    # A non-UTC clock still selects UTC calendar dates/hours.
    collector.test_time[0] = datetime(2026, 10, 31, 5, 30, 1, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    assert (await collector.snapshot("200", 1))["hourly_rows"] == today["hourly_rows"]


@pytest.mark.asyncio
async def test_snapshot_captures_one_utc_window_before_offloop_read(collector, monkeypatch):
    before_midnight = collector.clock()
    collector.record("command.attempts", channel_id="200", at=before_midnight)
    collector.record("command.attempts", channel_id="200", value=2, at=before_midnight + timedelta(seconds=2))
    await rows(collector)
    original_to_thread = asyncio.to_thread
    async def cross_midnight(function, *args, **kwargs):
        collector.test_time[0] = before_midnight + timedelta(seconds=2)
        return await original_to_thread(function, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(asyncio, "to_thread", cross_midnight)
        captured = await collector.snapshot("200", 1)
    assert totals(captured["rows"]) == totals(captured["hourly_rows"]) == {"command.attempts": 1}
    assert {r["day"] for r in captured["rows"]} == {"2026-10-30"}
    # Both management reads can request the same captured boundary after midnight.
    explicit = await collector.snapshot("200", 1, as_of=before_midnight)
    assert explicit["rows"] == captured["rows"]
    assert explicit["hourly_rows"] == captured["hourly_rows"]
    current = await collector.snapshot("200", 1)
    assert totals(current["rows"]) == totals(current["hourly_rows"]) == {"command.attempts": 2}


@pytest.mark.asyncio
async def test_hourly_coverage_does_not_bridge_disabled_gaps(collector):
    collector.test_time[0] = datetime(2026, 10, 31, 0, tzinfo=timezone.utc)
    collector._coverage_at = collector.clock()
    collector.connection("200", True)
    collector.test_time[0] += timedelta(hours=1)
    collector._checkpoint_coverage()
    collector._checkpoint_connection("200", collector.clock())
    await rows(collector)
    await collector.configure(False)
    collector.test_time[0] += timedelta(hours=2)
    collector._checkpoint_coverage()
    collector._checkpoint_connection("200", collector.clock())
    await collector.configure(True)
    collector.test_time[0] += timedelta(minutes=30)
    collector._checkpoint_coverage()
    collector._checkpoint_connection("200", collector.clock())
    await rows(collector)
    profile = await collector.snapshot("profile", 1)
    coverage = {r["day"]: r["value"] for r in profile["hourly_rows"] if r["metric"] == "coverage.seconds"}
    assert coverage == {"2026-10-31T00:00:00+00:00": 3600, "2026-10-31T03:00:00+00:00": 1800}
    assert totals((await collector.snapshot("200", 1))["hourly_rows"])["connection.seconds"] == 5400


@pytest.mark.asyncio
async def test_daily_only_upgrade_is_repeatable_and_never_backfills_hours(tmp_path):
    path = tmp_path / "old.analytics.sqlite3"
    now = [datetime(2026, 10, 31, 12, tzinfo=timezone.utc)]
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE daily (day TEXT NOT NULL, channel TEXT NOT NULL, dimension TEXT NOT NULL, metric TEXT NOT NULL, value REAL NOT NULL, PRIMARY KEY(channel,day,dimension,metric)) WITHOUT ROWID")
    con.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY,value TEXT NOT NULL)")
    con.execute("INSERT INTO metadata VALUES ('data_start','2026-10-01T00:00:00+00:00')")
    con.execute("INSERT INTO daily VALUES ('2026-10-31','200','ask','command.attempts',7)")
    con.execute("INSERT INTO daily VALUES ('2026-10-31','profile','','coverage.seconds',3600)")
    con.commit()
    con.close()
    for restart in range(2):
        analytics = Analytics(path, clock=lambda: now[0])
        await analytics.start()
        try:
            snapshot = await analytics.snapshot("200", 1)
            assert totals(snapshot["rows"])["command.attempts"] == 7 + restart
            assert totals(snapshot["hourly_rows"]).get("command.attempts", 0) == restart
            assert snapshot["metadata"]["data_start"] == "2026-10-01T00:00:00+00:00"
            assert snapshot["metadata"]["hourly_start"] == snapshot["metadata"]["new_users_start"] == "2026-10-31T12:00:00+00:00"
            if restart == 0:
                analytics.record("command.attempts", channel_id="200", dimension="ask")
                await rows(analytics)
        finally:
            await analytics.close()
    con = sqlite3.connect(path)
    assert {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")} == {"daily", "hourly", "metadata"}
    con.close()


@pytest.mark.asyncio
async def test_new_users_concurrent_first_messages_replay_rename_and_channel_isolation(collector, tmp_path):
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'personal.sqlite3'}")
    await database.initialize()
    users = UserRepository(database.session_factory)
    users.analytics = collector
    try:
        await asyncio.gather(*(users.upsert_seen("300", "synthetic", channel_id="200") for _ in range(20)))
        await users.upsert_seen("300", "renamed", channel_id="200")
        await users.upsert_seen("300", "renamed", channel_id="201")
        assert totals(await rows(collector))["users.new"] == 1
        assert totals(await rows(collector, "201"))["users.new"] == 1
        await users.upsert_seen("301", "different", channel_id="200")
        assert totals(await rows(collector))["users.new"] == 2
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_new_users_expired_presence_counts_again_without_historical_backfill(collector, tmp_path):
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'personal.sqlite3'}")
    await database.initialize()
    users = UserRepository(database.session_factory)
    try:
        await users.upsert_seen("300", "expired", datetime.now(timezone.utc) - timedelta(days=61), channel_id="200")
        await users.upsert_seen("301", "retained", channel_id="200")
        users.analytics = collector
        assert "users.new" not in totals(await rows(collector))
        await users.upsert_seen("300", "returned", channel_id="200")
        await users.upsert_seen("301", "returned", channel_id="200")
        assert totals(await rows(collector))["users.new"] == 1
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_new_users_optout_pending_epoch_and_collection_generation_guards(collector, tmp_path):
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'personal.sqlite3'}")
    await database.initialize()
    users = UserRepository(database.session_factory)
    users.analytics = collector
    try:
        await users.upsert_seen("300", "queued", channel_id="200")
        await users.opt_out("300")
        await users.withdraw_opt_out("300")
        assert await rows(collector) == []
        with users.storage_scope("300"):
            await users.opt_out("300")
            await users.withdraw_opt_out("300")
            assert await users.upsert_seen("300", "stale", channel_id="200") is None
        await users.opt_out("301")
        fresh_users = UserRepository(database.session_factory)
        fresh_users.analytics = collector
        assert await fresh_users.upsert_seen("301", "suppressed", channel_id="200") is None
        assert await rows(collector) == []
        for operation in (collector.reset, lambda: collector.configure(False)):
            async with users.policy.lock:
                pending = asyncio.create_task(users.upsert_seen("302", "pending", channel_id="200"))
                await asyncio.sleep(0)
                await operation()
            await pending
            assert await rows(collector) == []
        await collector.configure(True)
        # A presence retained while disabled is not backfilled on re-enable.
        await users.upsert_seen("302", "returned", channel_id="200")
        await users.upsert_seen("303", "new", channel_id="200")
        assert totals(await rows(collector))["users.new"] == 1
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_new_users_failed_commit_does_not_count(collector, tmp_path, monkeypatch):
    from sqlalchemy.ext.asyncio import AsyncSession
    from unittest.mock import AsyncMock
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'personal.sqlite3'}")
    await database.initialize()
    users = UserRepository(database.session_factory)
    users.analytics = collector
    try:
        with monkeypatch.context() as patch:
            patch.setattr(AsyncSession, "commit", AsyncMock(side_effect=OSError("synthetic failure")))
            with pytest.raises(OSError):
                await users.upsert_seen("300", "uncommitted", channel_id="200")
        assert await rows(collector) == []
        await users.upsert_seen("300", "committed", channel_id="200")
        assert totals(await rows(collector))["users.new"] == 1
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_new_users_optout_during_commit_cannot_leave_a_queued_contribution(collector, tmp_path, monkeypatch):
    from sqlalchemy.ext.asyncio import AsyncSession
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'personal.sqlite3'}")
    await database.initialize()
    users = UserRepository(database.session_factory)
    users.analytics = collector
    entered, release = asyncio.Event(), asyncio.Event()
    original_commit = AsyncSession.commit
    async def delayed_commit(session):
        entered.set()
        await release.wait()
        await original_commit(session)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(AsyncSession, "commit", delayed_commit)
            pending = asyncio.create_task(users.upsert_seen("300", "synthetic", channel_id="200"))
            await asyncio.wait_for(entered.wait(), 3)
            optout = asyncio.create_task(users.opt_out("300"))
            await asyncio.sleep(0)
            assert users.policy.privacy_epochs["300"] == 1
            release.set()
            await asyncio.wait_for(asyncio.gather(pending, optout), 3)
        assert await rows(collector) == []
        await users.withdraw_opt_out("300")
        await users.upsert_seen("300", "new_eligible_observation", channel_id="200")
        assert totals(await rows(collector))["users.new"] == 1
        collector.test_time[0] += timedelta(seconds=1)
        await collector.reset()
        snapshot = await collector.snapshot("200", 1)
        assert snapshot["rows"] == snapshot["hourly_rows"] == []
        assert snapshot["metadata"]["hourly_start"] == snapshot["metadata"]["new_users_start"] == collector.clock().isoformat()
    finally:
        release.set()
        await database.close()
