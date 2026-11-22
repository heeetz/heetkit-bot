"""Only synthetic profiles: versioned adoption, recovery and failure atomicity."""

from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import json
import sqlite3
import subprocess
import sys

import pytest

from app.database import migrations
from app.database.database import Database
from app.database.repository import AIMemoryRepository, UserRepository
from app.desktop_instance import DesktopAlreadyRunningError, desktop_instance_guard
from scripts.privacy_request import apply_request

NOW = datetime(2026, 10, 29, tzinfo=timezone.utc)


def test_experimental_v3_resets_only_monthly_leaderboards_and_keeps_exclusions(tmp_path):
    path = tmp_path / "experiment.sqlite3"
    migrations.initialize_schema(path)
    with sqlite3.connect(path) as connection:
        connection.execute("ALTER TABLE leaderboard_periods ADD COLUMN zone TEXT")
        connection.execute("DROP TABLE leaderboard_settings")
        connection.execute("CREATE TABLE leaderboard_settings (channel_id VARCHAR(32) NOT NULL PRIMARY KEY, zone TEXT NOT NULL, exclusions TEXT NOT NULL)")
        connection.execute("INSERT INTO leaderboard_settings VALUES ('200', 'Europe/London', '{\"otherbot\": \"300\"}')")
        connection.execute("INSERT INTO users VALUES (7, '200', '100', 'viewer', '2026-11-01', '2026-11-02')")
        connection.execute("INSERT INTO ai_memory_entries VALUES (8, '200', '100', 'question', 'answer', '2026-11-01')")
        connection.execute("INSERT INTO privacy_opt_outs VALUES ('500', 'private', NULL)")
        for kind, period, zone in (("stream", "123", None), ("month", "2026-11", "Europe/London")):
            connection.execute("INSERT INTO leaderboard_periods VALUES ('200', ?, ?, '2026-11-01', 1, NULL, ?)", (kind, period, zone))
            connection.execute("INSERT INTO leaderboard_counts VALUES ('200', ?, ?, '100', 10)", (kind, period))
    assert migrations.initialize_schema(path) == {"leaderboards": "experimental months reset to UTC"}
    assert migrations.initialize_schema(path) is None
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT * FROM leaderboard_counts").fetchall() == [("200", "stream", "123", "100", 10)]
        assert connection.execute("SELECT kind, period_id FROM leaderboard_periods").fetchall() == [("stream", "123")]
        assert connection.execute("SELECT * FROM leaderboard_settings").fetchall() == [("200", '{"otherbot": "300"}')]
        assert connection.execute("SELECT username FROM users").fetchall() == [("viewer",)]
        assert connection.execute("SELECT request_text, response_text FROM ai_memory_entries").fetchall() == [("question", "answer")]
        assert connection.execute("SELECT twitch_user_id FROM privacy_opt_outs").fetchall() == [("500",)]
OWNER_CHANNEL = "512901888"


def stamp(days=0):
    return (NOW - timedelta(days=days)).replace(tzinfo=None).isoformat(" ")


def read(path, sql):
    with closing(sqlite3.connect(path)) as connection:
        return connection.execute(sql).fetchall()


def schema_two(path):
    with closing(sqlite3.connect(path)) as connection, connection:
        for statement in migrations.SCHEMA_2_SQL:
            connection.execute(statement)
        connection.execute("PRAGMA user_version=2")
        connection.execute("INSERT INTO schema_metadata VALUES ('schema_version', '2')")


def seed(path):
    schema_two(path)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("INSERT INTO users VALUES (1, ?, '123', 'viewer', ?, ?)", (OWNER_CHANNEL, stamp(), stamp()))
        connection.execute("INSERT INTO ai_memory_entries VALUES (1, ?, '123', 'prompt', 'reply', ?)", (OWNER_CHANNEL, stamp()))
        connection.execute("INSERT INTO privacy_opt_outs VALUES ('777', 'suppressed', ?)", (stamp(),))


def test_schema_two_leaderboard_upgrade_recovers_then_retries(tmp_path):
    path = tmp_path / "published-schema.db"
    upgrade_now = datetime.now(timezone.utc)
    seed(path)

    def interrupt(connection):
        assert connection.execute("SELECT count(*) FROM leaderboard_counts").fetchone() == (0,)
        raise RuntimeError("Synthetic interruption")

    with pytest.raises(RuntimeError, match="Synthetic interruption"):
        migrations.initialize_schema(path, now=upgrade_now, before_commit=interrupt)
    assert read(path, "PRAGMA user_version") == [(2,)]
    _, backup, manifest = migrations._recovery_paths(path, version=2)
    assert json.loads(manifest.read_text())["sha256"] == hashlib.sha256(backup.read_bytes()).hexdigest()
    assert migrations.initialize_schema(path, now=upgrade_now) == {"leaderboards": "initialized empty"}
    migrated = path.read_bytes(), backup.read_bytes(), manifest.read_bytes()
    assert migrations.initialize_schema(path, now=upgrade_now) is None
    assert (path.read_bytes(), backup.read_bytes(), manifest.read_bytes()) == migrated
    for table in ("users", "ai_memory_entries", "privacy_opt_outs"):
        assert read(path, f"SELECT * FROM {table}") == read(backup, f"SELECT * FROM {table}")
    apply_request(path, "123", "opt-out")
    assert read(backup, "SELECT twitch_user_id FROM privacy_opt_outs ORDER BY 1") == [("123",), ("777",)]
    assert read(backup, "SELECT * FROM users") == []


@pytest.mark.parametrize("mode", ["delete", "wal"])
def test_wal_backup_and_ddl_rollback_are_atomic_and_retryable(tmp_path, mode):
    path = tmp_path / "synthetic.db"
    seed(path)
    with closing(sqlite3.connect(path)) as keeper:
        keeper.execute("PRAGMA journal_mode=" + mode)
        keeper.execute("UPDATE users SET username='wal_preserved' WHERE id=1")
        keeper.commit()
        def fail(connection):
            assert connection.execute("PRAGMA user_version").fetchone()[0] == migrations.SCHEMA_VERSION
            assert connection.execute("SELECT COUNT(*) FROM leaderboard_counts").fetchone() == (0,)
            raise RuntimeError("synthetic crash before commit")
        with pytest.raises(RuntimeError):
            migrations.initialize_schema(path, now=NOW, before_commit=fail)
        assert read(path, "PRAGMA user_version") == [(2,)]
        assert not read(path, "PRAGMA table_info(leaderboard_counts)")
        assert read(path, "SELECT COUNT(*) FROM users") == [(1,)]
        backup = migrations._recovery_paths(path, version=2)[1]
        assert read(backup, "SELECT username FROM users WHERE id=1") == [("wal_preserved",)]
        migrations.initialize_schema(path, now=NOW)
        assert read(path, "SELECT username FROM users WHERE id=1") == [("wal_preserved",)]


def test_process_exit_before_commit_leaves_schema_two_intact(tmp_path):
    path = tmp_path / "synthetic.db"
    seed(path)
    program = ("import os,sys; from datetime import datetime,timezone; from pathlib import Path; "
               "from app.database.migrations import initialize_schema; "
               "initialize_schema(Path(sys.argv[1]),now=datetime(2026,10,29,tzinfo=timezone.utc),before_commit=lambda c:os._exit(17))")
    result = subprocess.run([sys.executable, "-c", program, str(path)], timeout=15)
    assert result.returncode == 17
    assert read(path, "PRAGMA user_version") == [(2,)]
    assert read(path, "SELECT COUNT(*) FROM ai_memory_entries") == [(1,)]
    migrations.initialize_schema(path, now=NOW)
    assert read(path, "SELECT COUNT(*) FROM ai_memory_entries") == [(1,)]
    assert read(path, "PRAGMA user_version") == [(3,)]


@pytest.mark.parametrize("fault", ["future", "unknown", "corrupt"])
def test_unsupported_and_malformed_databases_stop_without_reset(tmp_path, fault):
    path = tmp_path / "synthetic.db"
    seed(path)
    if fault == "corrupt":
        path.write_bytes(b"PRIVATE invalid database bytes")
    else:
        statement = {"future": "PRAGMA user_version=999", "unknown": "CREATE TABLE unrelated(value TEXT)"}[fault]
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute(statement)
    before = path.read_bytes()
    with pytest.raises(migrations.DatabaseMigrationError) as error:
        migrations.initialize_schema(path, now=NOW)
    assert "PRIVATE" not in str(error.value)
    assert path.read_bytes() == before


def test_rejecting_unscoped_database_does_not_checkpoint_its_wal(tmp_path):
    path = tmp_path / "unscoped.db"
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.setconfig(sqlite3.SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE, True)
        connection.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, twitch_user_id VARCHAR(32))")
        connection.execute("INSERT INTO users VALUES (1, '123')")
    wal = path.with_name(path.name + "-wal")
    before = path.read_bytes(), wal.read_bytes()

    with pytest.raises(migrations.DatabaseMigrationError, match="Install HeetKit 1.6 once"):
        migrations.initialize_schema(path)
    assert (path.read_bytes(), wal.read_bytes()) == before


def test_backup_verification_failure_aborts_before_ddl(tmp_path, monkeypatch):
    path = tmp_path / "synthetic.db"
    seed(path)
    original = migrations._check_integrity
    def fail_backup(connection):
        if str(connection.execute("PRAGMA database_list").fetchone()[2]).endswith("schema-2.sqlite3"):
            raise migrations.DatabaseMigrationError("migrations.database_integrity_verification_failed_startup_stopped")
        original(connection)
    monkeypatch.setattr(migrations, "_check_integrity", fail_backup)
    with pytest.raises(migrations.DatabaseMigrationError):
        migrations.initialize_schema(path, now=NOW)
    assert read(path, "PRAGMA user_version") == [(2,)]
    assert read(path, "SELECT COUNT(*) FROM users") == [(1,)]
    assert not migrations._recovery_paths(path, version=2)[1].exists()


def test_fresh_schema_and_missing_constraints_are_detected(tmp_path):
    path = tmp_path / "fresh.db"
    migrations.initialize_schema(path, now=NOW)
    assert not migrations._recovery_paths(path, version=2)[0].exists()
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("DELETE FROM schema_metadata")
        connection.commit()
    with pytest.raises(migrations.DatabaseMigrationError, match="completion marker"):
        migrations.initialize_schema(path, now=NOW)


def test_active_sqlite_writer_refuses_migration_without_backup(tmp_path):
    path = tmp_path / "synthetic.db"
    seed(path)
    with closing(sqlite3.connect(path)) as writer:
        writer.execute("BEGIN IMMEDIATE")
        with pytest.raises(migrations.DatabaseMigrationError):
            migrations.initialize_schema(path, now=NOW)
        assert not migrations._recovery_paths(path, version=2)[1].exists()
        writer.rollback()
    assert read(path, "PRAGMA user_version") == [(2,)]


@pytest.mark.asyncio
async def test_migrated_seen_memory_and_optout_on_both_host_lifecycles(tmp_path, monkeypatch):
    from app.bot_runtime import BotRuntime
    from app.container import build_application
    from app.config.settings import Settings
    import logging
    path = tmp_path / "synthetic.db"
    # Recent timestamps relative to actual startup, without real data/providers.
    schema_two(path)
    recent = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(" ")
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("INSERT INTO users VALUES (1,?,'123','viewer',?,?)", (OWNER_CHANNEL, recent, recent))
        connection.execute("INSERT INTO ai_memory_entries VALUES (1,?,'123','question','answer',?)", (OWNER_CHANNEL, recent))
        connection.commit()
    monkeypatch.setenv("HEETKIT_DATA_DIR", str(tmp_path / "profile"))
    migrated = None
    for headless in (False, True):
        app = build_application(Settings(database_url="sqlite+aiosqlite:///" + str(path), gemini_api_key=None,
                                         deepseek_api_key=None, openai_api_key=None, twitch_client_secret=None))
        runtime = BotRuntime(app, logging.getLogger(__name__), headless=headless)
        try:
            await runtime.startup()
            assert (await app.services.users.get_by_username("viewer", channel_id=OWNER_CHANNEL)).twitch_user_id == "123"
            assert (await app.services.memory.get_recent("123", channel_id=OWNER_CHANNEL))[0].request_text == "question"
            assert await app.services.memory.get_recent("123", channel_id="222") == []
        finally:
            await runtime.shutdown()
        if migrated is None:
            migrated = path.read_bytes()
        else:
            assert path.read_bytes() == migrated
    apply_request(path, "123", "opt-out")
    backup = migrations._recovery_paths(path, version=2)[1]
    assert read(backup, "SELECT COUNT(*) FROM users") == [(0,)]
    assert read(backup, "SELECT COUNT(*) FROM ai_memory_entries") == [(0,)]
    assert ("123",) in read(backup, "SELECT twitch_user_id FROM privacy_opt_outs")
    migrations.maintain_recovery(path, now=datetime.now(timezone.utc) + timedelta(days=7, seconds=1))
    assert not backup.exists()


@pytest.mark.asyncio
async def test_exclusive_database_guard_and_restart_catchup(tmp_path):
    path = tmp_path / "synthetic.db"
    first = Database("sqlite+aiosqlite:///" + str(path))
    second = Database("sqlite+aiosqlite:///" + str(path))
    await first.initialize()
    try:
        with pytest.raises(migrations.DatabaseMigrationError, match="in use"):
            await second.initialize()
        with pytest.raises(DesktopAlreadyRunningError):
            apply_request(path, "123", "opt-out")
    finally:
        await second.close()
        await first.close()
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("INSERT INTO users VALUES (1,'100','123','viewer','2020-01-01','2020-01-01')")
        connection.execute("INSERT INTO ai_memory_entries VALUES (1,'100','123','question','answer','2020-01-01')")
        connection.commit()
    await second.initialize()
    try:
        assert await UserRepository(second.session_factory).get_by_username("viewer", channel_id="100") is None
        assert await AIMemoryRepository(second.session_factory).get_recent("123", 5, channel_id="100") == []
        assert read(path, "SELECT COUNT(*) FROM users") == [(0,)]
        assert read(path, "SELECT COUNT(*) FROM ai_memory_entries") == [(0,)]
    finally:
        await second.close()


@pytest.mark.parametrize("action", ["delete", "opt-in"])
def test_recovery_privacy_actions_preserve_their_exact_scope_and_fixed_expiry(tmp_path, action):
    path = tmp_path / "synthetic.db"
    seed(path)
    migrations.initialize_schema(path, now=datetime.now(timezone.utc))
    backup = migrations._recovery_paths(path, version=2)[1]
    manifest = migrations._recovery_paths(path, version=2)[2]
    expiry = json.loads(manifest.read_text())["expires_at"]
    if action == "opt-in":
        apply_request(path, "123", "opt-out")
    apply_request(path, "123", action)
    assert ("123",) not in read(backup, "SELECT twitch_user_id FROM privacy_opt_outs")
    assert read(backup, "SELECT COUNT(*) FROM ai_memory_entries WHERE twitch_user_id='123'") == [(0,)]
    metadata = json.loads(manifest.read_text())
    assert metadata["expires_at"] == expiry
    assert metadata["sha256"] == hashlib.sha256(backup.read_bytes()).hexdigest()


@pytest.mark.asyncio
async def test_cancelled_startup_keeps_guard_until_migration_worker_finishes(tmp_path, monkeypatch):
    import asyncio
    import threading
    path = tmp_path / "synthetic.db"
    entered, release = threading.Event(), threading.Event()
    original = migrations.initialize_schema
    def paused(*args):
        entered.set()
        assert release.wait(5)
        return original(*args)
    monkeypatch.setattr("app.database.database.initialize_schema", paused)
    first = Database("sqlite+aiosqlite:///" + str(path))
    second = Database("sqlite+aiosqlite:///" + str(path))
    pending = asyncio.create_task(first.initialize())
    try:
        while not entered.is_set():
            await asyncio.sleep(0.001)
        pending.cancel()
        await asyncio.sleep(0)
        with pytest.raises(migrations.DatabaseMigrationError, match="in use"):
            await second.initialize()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert read(path, "PRAGMA user_version") == [(migrations.SCHEMA_VERSION,)]
    finally:
        release.set()
        await first.close()
        await second.close()


@pytest.mark.asyncio
async def test_database_beside_settings_does_not_collide_with_own_profile_guard(tmp_path):
    path = tmp_path / "synthetic.db"
    database = Database("sqlite+aiosqlite:///" + str(path))
    try:
        with desktop_instance_guard(tmp_path / "app_settings.json"):
            await database.initialize()
            assert read(path, "PRAGMA user_version") == [(migrations.SCHEMA_VERSION,)]
    finally:
        await database.close()


def test_expired_recovery_cleanup_only_removes_verified_owned_files(tmp_path):
    path = tmp_path / "synthetic.db"
    seed(path)
    migrations.initialize_schema(path, now=NOW)
    folder, backup, manifest = migrations._recovery_paths(path, version=2)
    unrelated = folder / "operator-notes.txt"
    unrelated.write_text("keep this manually owned file")
    source = path.read_bytes()
    migrations.maintain_recovery(path, now=NOW + timedelta(days=7))
    assert not backup.exists() and not manifest.exists()
    assert unrelated.read_text() == "keep this manually owned file"
    assert path.read_bytes() == source


@pytest.mark.parametrize("fault", ["version", "checksum", "expiry", "invalid", "hardlink", "missing_digest"])
def test_cleanup_refuses_unowned_or_unverifiable_recovery_files(tmp_path, fault):
    import os
    path = tmp_path / "synthetic.db"
    seed(path)
    migrations.initialize_schema(path, now=NOW)
    _, backup, manifest = migrations._recovery_paths(path, version=2)
    metadata = json.loads(manifest.read_text())
    if fault == "version":
        metadata["version"] = 99
    elif fault == "checksum":
        backup.write_bytes(b"unrelated operator file")
    elif fault == "expiry":
        metadata["expires_at"] = (NOW + timedelta(days=8)).isoformat()
    elif fault == "hardlink":
        os.link(backup, tmp_path / "operator-copy.sqlite3")
    elif fault == "missing_digest":
        metadata.pop("sha256")
        backup.unlink()  # An orphan still needs a complete ownership manifest.
    manifest.write_text("[]" if fault == "invalid" else json.dumps(metadata))
    before = backup.read_bytes() if backup.exists() else None, manifest.read_bytes()
    with pytest.raises(migrations.DatabaseMigrationError):
        migrations.maintain_recovery(path, now=NOW + timedelta(days=10))
    assert (backup.read_bytes() if backup.exists() else None, manifest.read_bytes()) == before


def test_failed_upgrade_retry_reuses_existing_cleanup_for_expired_snapshot(tmp_path):
    path = tmp_path / "synthetic.db"
    seed(path)
    def fail(_):
        raise RuntimeError("synthetic interruption")
    with pytest.raises(RuntimeError):
        migrations.initialize_schema(path, now=NOW, before_commit=fail)
    folder, _, manifest = migrations._recovery_paths(path, version=2)
    (folder / "operator-notes.txt").write_text("keep")
    later = NOW + timedelta(days=8)
    migrations.initialize_schema(path, now=later)
    assert json.loads(manifest.read_text())["created_at"] == later.isoformat()
    assert (folder / "operator-notes.txt").read_text() == "keep"


@pytest.mark.parametrize("expired", [False, True])
def test_recovery_cleanup_resumes_after_only_expired_snapshot_was_removed(tmp_path, expired):
    path = tmp_path / "synthetic.db"
    seed(path)
    migrations.initialize_schema(path, now=NOW)
    _, backup, manifest = migrations._recovery_paths(path, version=2)
    backup.unlink()
    if expired:
        migrations.maintain_recovery(path, now=NOW + timedelta(days=7))
        assert not manifest.exists()
    else:
        with pytest.raises(migrations.DatabaseMigrationError):
            migrations.maintain_recovery(path, now=NOW + timedelta(days=6))
        assert manifest.exists()
