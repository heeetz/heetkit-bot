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
OWNER_CHANNEL = "512901888"


def stamp(days=0):
    return (NOW - timedelta(days=days)).replace(tzinfo=None).isoformat(" ")


def legacy(path, *, scoped=False, suppression=True):
    with closing(sqlite3.connect(path)) as connection:
        extra = "channel_id VARCHAR(32)," if scoped else ""
        connection.execute(f"CREATE TABLE users (id INTEGER PRIMARY KEY, {extra} twitch_user_id VARCHAR(32), username VARCHAR(64), created_at DATETIME, last_seen_at DATETIME)")
        connection.execute(f"CREATE TABLE ai_memory_entries (id INTEGER PRIMARY KEY, {extra} twitch_user_id VARCHAR(32), request_text VARCHAR(500), response_text VARCHAR(500), created_at DATETIME)")
        if suppression:
            connection.execute("CREATE TABLE privacy_opt_outs (twitch_user_id VARCHAR(32) PRIMARY KEY)")
            connection.execute("INSERT INTO privacy_opt_outs VALUES ('999')")
        connection.commit()


def map_channel(path, value=OWNER_CHANNEL):
    (path.parent / "legacy-channel-mapping.json").write_text(json.dumps({"version": 1, "channel_id": value}), encoding="utf-8")


def read(path, sql):
    with closing(sqlite3.connect(path)) as connection:
        return connection.execute(sql).fetchall()


def seed(path, *, scoped=False):
    legacy(path, scoped=scoped)
    users = [(1, "123", "viewer", stamp(120), stamp(1)),
             (2, "456", "expired", stamp(120), stamp(60)),
             (3, "999", "suppressed", stamp(2), stamp(1))]
    ai = [(i, "123", f"question-{i}", f"answer-{i}", stamp(i)) for i in range(1, 5)]
    ai += [(5, "123", "expired", "answer", stamp(60)), (6, "999", "suppressed", "answer", stamp(1))]
    if scoped:
        users = [(row[0], None, *row[1:]) for row in users] + [(4, "222", "123", "other_channel", stamp(20), stamp(1))]
        ai = [(row[0], None, *row[1:]) for row in ai] + [(7, "222", "123", "scoped", "answer", stamp(1))]
    with closing(sqlite3.connect(path)) as connection:
        connection.executemany("INSERT INTO users VALUES (" + ",".join("?" for _ in users[0]) + ")", users)
        connection.executemany("INSERT INTO ai_memory_entries VALUES (" + ",".join("?" for _ in ai[0]) + ")", ai)
        connection.commit()


@pytest.mark.parametrize("scoped", [False, True])
def test_verified_adoption_preserves_fields_dates_scope_suppression_and_counts(tmp_path, scoped):
    path = tmp_path / "synthetic.db"
    seed(path, scoped=scoped)
    map_channel(path)
    report = migrations.initialize_schema(path, 2, now=NOW)
    assert report["users"] == dict(source=4 if scoped else 3, retained=2 if scoped else 1, opted_out=1, expired=1, count_cap=0)
    assert report["ai_memory_entries"] == dict(source=7 if scoped else 6, retained=3 if scoped else 2, opted_out=1, expired=1, count_cap=2)
    users = read(path, "SELECT id, channel_id, twitch_user_id, username, created_at, last_seen_at FROM users ORDER BY id")
    assert users[0] == (1, OWNER_CHANNEL, "123", "viewer", stamp(120), stamp(1))
    if scoped:
        assert users[1][1] == "222"
    assert read(path, "SELECT request_text, created_at FROM ai_memory_entries WHERE channel_id='512901888' ORDER BY id") == [("question-1", stamp(1)), ("question-2", stamp(2))]
    assert read(path, "SELECT * FROM privacy_opt_outs") == [("999",)]
    assert read(path, "PRAGMA user_version") == [(migrations.SCHEMA_VERSION,)]
    folder, backup, manifest = migrations._recovery_paths(path)
    metadata = json.loads(manifest.read_text())
    assert metadata["sha256"] == hashlib.sha256(backup.read_bytes()).hexdigest()
    assert metadata["counts"]["ai_memory_entries"] == (7 if scoped else 6)
    assert read(backup, "PRAGMA integrity_check") == [("ok",)]
    before = (backup.read_bytes(), manifest.read_bytes())
    assert migrations.initialize_schema(path, 2, now=NOW + timedelta(days=1)) is None
    assert (backup.read_bytes(), manifest.read_bytes()) == before
    assert len(list(folder.glob("*.sqlite3"))) == 1


@pytest.mark.parametrize("mode", ["delete", "wal"])
def test_wal_backup_and_ddl_rollback_are_atomic_and_retryable(tmp_path, mode):
    path = tmp_path / "synthetic.db"
    seed(path)
    map_channel(path)
    with closing(sqlite3.connect(path)) as keeper:
        keeper.execute("PRAGMA journal_mode=" + mode)
        keeper.execute("UPDATE users SET username='wal_preserved' WHERE id=1")
        keeper.commit()
        def fail(connection):
            assert connection.execute("PRAGMA user_version").fetchone()[0] == migrations.SCHEMA_VERSION
            assert "channel_id" in [row[1] for row in connection.execute("PRAGMA table_info(users)")]
            raise RuntimeError("synthetic crash before commit")
        with pytest.raises(RuntimeError):
            migrations.initialize_schema(path, 2, now=NOW, before_commit=fail)
        assert read(path, "PRAGMA user_version") == [(0,)]
        assert "channel_id" not in [row[1] for row in read(path, "PRAGMA table_info(users)")]
        assert read(path, "SELECT COUNT(*) FROM users") == [(3,)]
        backup = migrations._recovery_paths(path)[1]
        assert read(backup, "SELECT username FROM users WHERE id=1") == [("wal_preserved",)]
        migrations.initialize_schema(path, 2, now=NOW)
        assert read(path, "SELECT username FROM users WHERE id=1") == [("wal_preserved",)]


def test_process_exit_before_commit_leaves_complete_legacy_schema(tmp_path):
    path = tmp_path / "synthetic.db"
    seed(path)
    map_channel(path)
    program = ("import os,sys; from datetime import datetime,timezone; from pathlib import Path; "
               "from app.database.migrations import initialize_schema; "
               "initialize_schema(Path(sys.argv[1]),2,now=datetime(2026,10,29,tzinfo=timezone.utc),before_commit=lambda c:os._exit(17))")
    result = subprocess.run([sys.executable, "-c", program, str(path)], timeout=15)
    assert result.returncode == 17
    assert read(path, "PRAGMA user_version") == [(0,)]
    assert read(path, "SELECT COUNT(*) FROM ai_memory_entries") == [(6,)]
    migrations.initialize_schema(path, 2, now=NOW)
    assert read(path, "SELECT COUNT(*) FROM ai_memory_entries") == [(2,)]


@pytest.mark.parametrize("fault", ["mapping", "malformed", "future", "unknown", "corrupt"])
def test_unsupported_and_malformed_databases_stop_without_reset(tmp_path, fault):
    path = tmp_path / "synthetic.db"
    seed(path)
    if fault != "mapping":
        map_channel(path)
    if fault == "corrupt":
        path.write_bytes(b"not a sqlite database")
    elif fault != "mapping":
        statement = {"malformed": "UPDATE ai_memory_entries SET created_at='PRIVATE invalid date' WHERE id=1",
                     "future": "PRAGMA user_version=999", "unknown": "CREATE TABLE unrelated(value TEXT)"}[fault]
        with closing(sqlite3.connect(path)) as connection:
            connection.execute(statement)
            connection.commit()
    before = path.read_bytes()
    with pytest.raises(migrations.DatabaseMigrationError) as error:
        migrations.initialize_schema(path, 2, now=NOW)
    assert "PRIVATE" not in str(error.value)
    assert path.read_bytes() == before


def test_backup_verification_failure_aborts_before_ddl(tmp_path, monkeypatch):
    path = tmp_path / "synthetic.db"
    seed(path)
    map_channel(path)
    original = migrations._check_integrity
    def fail_backup(connection):
        if str(connection.execute("PRAGMA database_list").fetchone()[2]).endswith("schema-0.sqlite3"):
            raise migrations.DatabaseMigrationError("Synthetic verification failure")
        original(connection)
    monkeypatch.setattr(migrations, "_check_integrity", fail_backup)
    with pytest.raises(migrations.DatabaseMigrationError):
        migrations.initialize_schema(path, 2, now=NOW)
    assert read(path, "PRAGMA user_version") == [(0,)]
    assert read(path, "SELECT COUNT(*) FROM users") == [(3,)]
    assert not migrations._recovery_paths(path)[1].exists()


def test_fresh_schema_and_missing_constraints_are_detected(tmp_path):
    path = tmp_path / "fresh.db"
    migrations.initialize_schema(path, 100, now=NOW)
    assert not migrations._recovery_paths(path)[0].exists()
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("DELETE FROM schema_metadata")
        connection.commit()
    with pytest.raises(migrations.DatabaseMigrationError, match="completion marker"):
        migrations.initialize_schema(path, 100, now=NOW)


def test_active_sqlite_writer_refuses_migration_without_backup(tmp_path):
    path = tmp_path / "synthetic.db"
    seed(path)
    map_channel(path)
    with closing(sqlite3.connect(path)) as writer:
        writer.execute("BEGIN IMMEDIATE")
        with pytest.raises(migrations.DatabaseMigrationError):
            migrations.initialize_schema(path, 2, now=NOW)
        assert not migrations._recovery_paths(path)[1].exists()
        writer.rollback()
    assert read(path, "PRAGMA user_version") == [(0,)]


@pytest.mark.asyncio
async def test_migrated_seen_memory_and_optout_on_both_host_lifecycles(tmp_path, monkeypatch):
    from app.bot_runtime import BotRuntime
    from app.container import build_application
    from app.config.settings import Settings
    import logging
    path = tmp_path / "synthetic.db"
    # Recent timestamps relative to actual startup, without real data/providers.
    legacy(path)
    recent = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(" ")
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("INSERT INTO users VALUES (1,'123','viewer',?,?)", (recent, recent))
        connection.execute("INSERT INTO ai_memory_entries VALUES (1,'123','question','answer',?)", (recent,))
        connection.commit()
    map_channel(path)
    monkeypatch.setenv("HEETKIT_DATA_DIR", str(tmp_path / "profile"))
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
    apply_request(path, "123", "opt-out")
    backup = migrations._recovery_paths(path)[1]
    assert read(backup, "SELECT COUNT(*) FROM users") == [(0,)]
    assert read(backup, "SELECT COUNT(*) FROM ai_memory_entries") == [(0,)]
    assert ("123",) in read(backup, "SELECT * FROM privacy_opt_outs")
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
    map_channel(path)
    migrations.initialize_schema(path, 100, now=datetime.now(timezone.utc))
    backup = migrations._recovery_paths(path)[1]
    manifest = migrations._recovery_paths(path)[2]
    expiry = json.loads(manifest.read_text())["expires_at"]
    if action == "opt-in":
        apply_request(path, "123", "opt-out")
    apply_request(path, "123", action)
    assert ("123",) not in read(backup, "SELECT * FROM privacy_opt_outs")
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
    map_channel(path)
    migrations.initialize_schema(path, 100, now=NOW)
    folder, backup, manifest = migrations._recovery_paths(path)
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
    map_channel(path)
    migrations.initialize_schema(path, 100, now=NOW)
    _, backup, manifest = migrations._recovery_paths(path)
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
    map_channel(path)
    def fail(_):
        raise RuntimeError("synthetic interruption")
    with pytest.raises(RuntimeError):
        migrations.initialize_schema(path, 100, now=NOW, before_commit=fail)
    folder, _, manifest = migrations._recovery_paths(path)
    (folder / "operator-notes.txt").write_text("keep")
    later = NOW + timedelta(days=8)
    migrations.initialize_schema(path, 100, now=later)
    assert json.loads(manifest.read_text())["created_at"] == later.isoformat()
    assert (folder / "operator-notes.txt").read_text() == "keep"


@pytest.mark.parametrize("expired", [False, True])
def test_recovery_cleanup_resumes_after_only_expired_snapshot_was_removed(tmp_path, expired):
    path = tmp_path / "synthetic.db"
    seed(path)
    map_channel(path)
    migrations.initialize_schema(path, 100, now=NOW)
    _, backup, manifest = migrations._recovery_paths(path)
    backup.unlink()
    if expired:
        migrations.maintain_recovery(path, now=NOW + timedelta(days=7))
        assert not manifest.exists()
    else:
        with pytest.raises(migrations.DatabaseMigrationError):
            migrations.maintain_recovery(path, now=NOW + timedelta(days=6))
        assert manifest.exists()
