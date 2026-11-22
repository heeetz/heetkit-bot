"""Versioned SQLite upgrade and private recovery copies (standard library only).

Called before any async database work, under the application's exclusive guard.
No selected-channel inference, profile discovery, credentials or provider access.
"""

from __future__ import annotations

from app.errors import UserError
import asyncio
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3

SCHEMA_VERSION = 3
RECOVERY_DAYS = 7
SCHEMA_2_COLUMNS = {
    "users": ("id", "channel_id", "twitch_user_id", "username", "created_at", "last_seen_at"),
    "ai_memory_entries": ("id", "channel_id", "twitch_user_id", "request_text", "response_text", "created_at"),
    "privacy_opt_outs": ("twitch_user_id", "username", "opted_out_at"),
    "schema_metadata": ("name", "value"),
}
LEADERBOARD_COLUMNS = {
    "leaderboard_periods": ("channel_id", "kind", "period_id", "started_at", "partial", "ends_at"),
    "leaderboard_counts": ("channel_id", "kind", "period_id", "twitch_user_id", "messages"),
    "leaderboard_settings": ("channel_id", "exclusions"),
}
TABLE_COLUMNS = {**SCHEMA_2_COLUMNS, **LEADERBOARD_COLUMNS}
EXPERIMENTAL_V3_COLUMNS = {
    **TABLE_COLUMNS,
    "leaderboard_periods": (*LEADERBOARD_COLUMNS["leaderboard_periods"], "zone"),
    "leaderboard_settings": ("channel_id", "zone", "exclusions"),
}
LEADERBOARD_SQL = (
    "CREATE TABLE leaderboard_periods (channel_id VARCHAR(32) NOT NULL, kind TEXT NOT NULL, "
    "period_id TEXT NOT NULL, started_at DATETIME NOT NULL, partial INTEGER NOT NULL CHECK(partial IN (0, 1)), "
    "ends_at DATETIME, "
    "PRIMARY KEY(channel_id, kind))",
    "CREATE TABLE leaderboard_counts (channel_id VARCHAR(32) NOT NULL, kind TEXT NOT NULL, "
    "period_id TEXT NOT NULL, twitch_user_id VARCHAR(32) NOT NULL, "
    "messages INTEGER NOT NULL CHECK(messages > 0), PRIMARY KEY(channel_id, kind, period_id, twitch_user_id))",
    "CREATE INDEX ix_leaderboard_counts_user ON leaderboard_counts(twitch_user_id)",
    "CREATE TABLE leaderboard_settings (channel_id VARCHAR(32) NOT NULL PRIMARY KEY, exclusions TEXT NOT NULL)",
)
SCHEMA_2_SQL = (
    "CREATE TABLE users (id INTEGER NOT NULL PRIMARY KEY, channel_id VARCHAR(32) NOT NULL, "
    "twitch_user_id VARCHAR(32) NOT NULL, username VARCHAR(64) NOT NULL, created_at DATETIME NOT NULL, "
    "last_seen_at DATETIME NOT NULL, UNIQUE(channel_id, twitch_user_id))",
    "CREATE INDEX ix_users_channel_id ON users(channel_id)",
    "CREATE INDEX ix_users_username ON users(username)",
    "CREATE TABLE ai_memory_entries (id INTEGER NOT NULL PRIMARY KEY, channel_id VARCHAR(32) NOT NULL, "
    "twitch_user_id VARCHAR(32) NOT NULL, request_text VARCHAR(500) NOT NULL, "
    "response_text VARCHAR(500) NOT NULL, created_at DATETIME NOT NULL)",
    "CREATE INDEX ix_ai_memory_scope_time ON ai_memory_entries(channel_id, twitch_user_id, created_at, id)",
    "CREATE TABLE privacy_opt_outs (twitch_user_id VARCHAR(32) NOT NULL PRIMARY KEY, username VARCHAR(64), opted_out_at DATETIME)",
    "CREATE TABLE schema_metadata (name TEXT NOT NULL PRIMARY KEY, value TEXT NOT NULL)",
)
SCHEMA_SQL = SCHEMA_2_SQL + LEADERBOARD_SQL


class DatabaseMigrationError(UserError, RuntimeError):
    """Fixed diagnostics only: sqlite exception strings may contain private values."""

    @property
    def operator_message(self):
        return (f"{self} Close every HeetKit process using this profile before retrying. "
                "Keep the database and recovery copies; do not delete them to bypass this error. "
                "See Data and privacy: Versioned database upgrade and recovery.")


async def run_sqlite_work(operation, *args, **kwargs):
    """Retain caller-owned guards/locks until a cancelled worker really finishes."""
    task = asyncio.create_task(asyncio.to_thread(operation, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            await task
        except Exception:
            pass  # Cancellation still stops startup; no migration success is reported.
        raise


def _tables(connection):
    return {row[0]: tuple(column[1] for column in connection.execute(f'PRAGMA table_info("{row[0]}")'))
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}


def _check_integrity(connection):
    if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        raise DatabaseMigrationError("migrations.database_integrity_verification_failed_startup_stopped")
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise DatabaseMigrationError("migrations.database_relationship_verification_failed_startup_stopped")


def _snapshot(connection):
    tables = _tables(connection)
    counts = {}
    digest = hashlib.sha256()
    for table in sorted(tables):
        if table not in TABLE_COLUMNS:
            raise DatabaseMigrationError("migrations.unsupported_database_tables_startup_stopped")
        order = ','.join(str(index) for index in range(1, len(tables[table]) + 1)) if table in LEADERBOARD_COLUMNS else '1'
        rows = connection.execute(f'SELECT * FROM "{table}" ORDER BY {order}').fetchall()
        counts[table] = len(rows)
        digest.update(json.dumps([table, tables[table], rows], ensure_ascii=True).encode())
    return counts, digest.hexdigest()


def _private_json(path, payload):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as stream:
        json.dump(payload, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())


def _recovery_paths(path, version):
    folder = path.parent / (path.name + ".recovery")
    if folder.is_symlink() or folder.is_junction() or (folder.exists() and folder.resolve() != folder.absolute()):
        raise DatabaseMigrationError("migrations.unsafe_database_recovery_directory_startup_stopped")
    return folder, folder / f"schema-{version}.sqlite3", folder / f"schema-{version}.json"


def _backup(path, connection, now):
    maintain_recovery(path, now=now)
    folder, target, manifest = _recovery_paths(path, 2)
    folder.mkdir(mode=0o700, exist_ok=True)
    if target.is_symlink() or manifest.is_symlink():
        raise DatabaseMigrationError("migrations.unsafe_database_recovery_file_startup_stopped")
    counts, logical_checksum = _snapshot(connection)
    if target.exists() or manifest.exists():
        # A failed/interrupted migration can reuse only its exact verified snapshot.
        try:
            metadata = json.loads(manifest.read_text(encoding="utf-8"))
            if (metadata["source_checksum"] != logical_checksum or metadata["counts"] != counts
                    or metadata["sha256"] != hashlib.sha256(target.read_bytes()).hexdigest()
                    or _date(metadata["expires_at"]) <= now):
                raise ValueError
            with closing(sqlite3.connect(target.as_uri() + "?mode=ro", uri=True)) as backup:
                _check_integrity(backup)
                if _snapshot(backup) != (counts, logical_checksum):
                    raise ValueError
            return
        except (OSError, ValueError, KeyError, sqlite3.Error):
            raise DatabaseMigrationError("migrations.existing_recovery_snapshot_cannot_be_verified_preserve_it_and") from None
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
    try:
        # The caller holds BEGIN IMMEDIATE, preventing all other writers. A
        # separate read connection includes committed WAL pages in the backup API.
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as source:
            with closing(sqlite3.connect(target)) as backup:
                source.backup(backup)
                _check_integrity(backup)
                if _snapshot(backup) != (counts, logical_checksum):
                    raise DatabaseMigrationError("migrations.recovery_snapshot_counts_checksum_verification_failed")
        _private_json(manifest, {"version": 1, "created_at": now.isoformat(),
                      "expires_at": (now + timedelta(days=RECOVERY_DAYS)).isoformat(),
                      "counts": counts, "source_checksum": logical_checksum,
                      "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
    except BaseException:
        # An unverified copy is not a recovery artifact; the source is unchanged.
        target.unlink(missing_ok=True)
        manifest.unlink(missing_ok=True)
        raise


def _date(value):
    result = datetime.fromisoformat(value)
    return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)


def _validate_schema(connection, version, *, experimental=False):
    expected_columns = SCHEMA_2_COLUMNS if version == 2 else EXPERIMENTAL_V3_COLUMNS if experimental else TABLE_COLUMNS
    if _tables(connection) != expected_columns:
        raise DatabaseMigrationError("migrations.unsupported_database_schema_startup_stopped")
    for table in expected_columns:
        definition = connection.execute(f'PRAGMA table_info("{table}")').fetchall()
        expected_types = {"id": "INTEGER", "channel_id": "VARCHAR(32)", "twitch_user_id": "VARCHAR(32)",
                          "username": "VARCHAR(64)", "request_text": "VARCHAR(500)", "response_text": "VARCHAR(500)",
                          "created_at": "DATETIME", "last_seen_at": "DATETIME", "opted_out_at": "DATETIME", "name": "TEXT", "value": "TEXT",
                          "kind": "TEXT", "period_id": "TEXT", "started_at": "DATETIME", "partial": "INTEGER", "messages": "INTEGER",
                          "ends_at": "DATETIME", "zone": "TEXT", "exclusions": "TEXT"}
        optional = {"privacy_opt_outs": {"username", "opted_out_at"}, "leaderboard_periods": {"ends_at", "zone"}}.get(table, set())
        primary_key = {"leaderboard_periods": ("channel_id", "kind"),
                       "leaderboard_counts": ("channel_id", "kind", "period_id", "twitch_user_id")}.get(table, (definition[0][1],))
        if (any((not column[3] and column[1] not in optional) or column[2].upper() != expected_types[column[1]] for column in definition)
                or tuple(column[1] for column in sorted(definition, key=lambda field: field[5]) if column[5]) != primary_key):
            raise DatabaseMigrationError("migrations.invalid_database_field_constraints_startup_stopped")
    if connection.execute("SELECT COUNT(*) FROM sqlite_master WHERE type IN ('trigger','view')").fetchone()[0]:
        raise DatabaseMigrationError("migrations.unsupported_database_objects_startup_stopped")
    # Verify required identity uniqueness, not just matching column names.
    indexes = connection.execute("PRAGMA index_list(users)").fetchall()
    unique_keys = {tuple(row[2] for row in connection.execute(f'PRAGMA index_info("{index[1]}")'))
                   for index in indexes if index[2]}
    if ("channel_id", "twitch_user_id") not in unique_keys or ("twitch_user_id",) in unique_keys:
        raise DatabaseMigrationError("migrations.invalid_channel_identity_constraints_startup_stopped")
    marker = connection.execute("SELECT value FROM schema_metadata WHERE name='schema_version'").fetchone()
    if marker != (str(version),):
        raise DatabaseMigrationError("migrations.database_completion_marker_is_missing_startup_stopped")


def _create(connection):
    for statement in SCHEMA_SQL:
        connection.execute(statement)
    connection.execute("INSERT INTO schema_metadata VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def initialize_schema(path: Path, *, now=None, before_commit=None):
    """All DDL/data/version changes share an explicit, tested SQLite transaction."""
    path = path.resolve()
    now = now or datetime.now(timezone.utc)
    try:
        with closing(sqlite3.connect(path, timeout=0, isolation_level=None)) as connection:
            # Closing a rejected database must not checkpoint its pending WAL.
            connection.setconfig(sqlite3.SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE, True)
            connection.execute("PRAGMA secure_delete=ON")
            connection.execute("BEGIN IMMEDIATE")
            try:
                tables = _tables(connection)
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                if (version or tables) and (version < 2 or "schema_metadata" not in tables):
                    raise DatabaseMigrationError("database.update_through_1_6")
                _check_integrity(connection)
                if connection.execute("SELECT COUNT(*) FROM sqlite_master WHERE type IN ('trigger','view')").fetchone()[0]:
                    raise DatabaseMigrationError("migrations.unsupported_database_objects_startup_stopped")
                report = None
                if version == 2:
                    _validate_schema(connection, version)
                    _backup(path, connection, now)
                    for statement in LEADERBOARD_SQL:
                        connection.execute(statement)
                    connection.execute("UPDATE schema_metadata SET value=? WHERE name='schema_version'", (str(SCHEMA_VERSION),))
                    connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                    report = {"leaderboards": "initialized empty"}
                elif version == SCHEMA_VERSION:
                    if tables == EXPERIMENTAL_V3_COLUMNS:
                        _validate_schema(connection, version, experimental=True)
                        # Discard only local experimental monthly counts. Stream
                        # periods and channel exclusion IDs keep their meaning.
                        connection.execute("DELETE FROM leaderboard_counts WHERE kind='month'")
                        connection.execute("DELETE FROM leaderboard_periods WHERE kind='month'")
                        connection.execute("ALTER TABLE leaderboard_periods DROP COLUMN zone")
                        connection.execute("ALTER TABLE leaderboard_settings DROP COLUMN zone")
                        report = {"leaderboards": "experimental months reset to UTC"}
                elif version != 0:
                    raise DatabaseMigrationError("migrations.unsupported_database_version_use_a_compatible_application")
                elif not tables:
                    _create(connection)
                _validate_schema(connection, SCHEMA_VERSION)
                _check_integrity(connection)
                if before_commit is not None:
                    before_commit(connection)
                connection.commit()
                connection.setconfig(sqlite3.SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE, False)
                return report
            except BaseException:
                connection.rollback()
                raise
    except DatabaseMigrationError:
        raise
    except (sqlite3.Error, OSError, ValueError, TypeError):
        raise DatabaseMigrationError("migrations.database_initialization_backup_failed_startup_stopped_with_existing_data") from None


def maintain_recovery(path: Path, suppressed=(), *, deleted=(), withdrawn=(), now=None):
    for version in (0, 1, 2):
        _maintain_recovery(path, suppressed, deleted=deleted, withdrawn=withdrawn, now=now, version=version)


def _maintain_recovery(path: Path, suppressed=(), *, deleted=(), withdrawn=(), now=None, version):
    """Expire only our fixed recovery files; scrub known deletions before restore."""
    now = now or datetime.now(timezone.utc)
    folder, target, manifest = _recovery_paths(path.resolve(), version)
    if not target.exists() and not manifest.exists():
        return
    if target.is_symlink() or manifest.is_symlink():
        raise DatabaseMigrationError("migrations.unsafe_database_recovery_file")
    try:
        metadata = json.loads(manifest.read_text(encoding="utf-8"))
        if (not isinstance(metadata, dict) or type(metadata.get("version")) is not int or metadata["version"] != 1
                or not isinstance(metadata.get("source_checksum"), str)
                or re.fullmatch(r"[0-9a-f]{64}", metadata["source_checksum"]) is None
                or not isinstance(metadata.get("sha256"), str)
                or re.fullmatch(r"[0-9a-f]{64}", metadata["sha256"]) is None
                or not isinstance(metadata.get("counts"), dict)
                or not {"users", "ai_memory_entries"} <= metadata["counts"].keys()
                or set(metadata["counts"]) - TABLE_COLUMNS.keys()
                or any(type(count) is not int or count < 0 for count in metadata["counts"].values())):
            raise ValueError
        created, expiry = _date(metadata["created_at"]), _date(metadata["expires_at"])
        if expiry != created + timedelta(days=RECOVERY_DAYS):
            raise ValueError
        # The fixed names alone do not establish ownership. Verify this generated
        # manifest and its regular, unlinked snapshot before deleting either file.
        if not manifest.is_file() or manifest.stat().st_nlink != 1:
            raise ValueError
        if target.exists():
            if (not target.is_file() or target.stat().st_nlink != 1
                    or metadata["sha256"] != hashlib.sha256(target.read_bytes()).hexdigest()):
                raise ValueError
        elif now < expiry:
            raise ValueError
        if now >= expiry:
            target.unlink(missing_ok=True)
            manifest.unlink()
            return
        if suppressed or deleted or withdrawn:
            with closing(sqlite3.connect(target.as_uri() + "?mode=rw", uri=True, timeout=0)) as backup:
                backup.execute("PRAGMA secure_delete=ON")
                _check_integrity(backup)
                with backup:
                    backup.execute("BEGIN IMMEDIATE")
                    backup.execute("CREATE TABLE IF NOT EXISTS privacy_opt_outs (twitch_user_id VARCHAR(32) PRIMARY KEY)")
                    for user_id in suppressed:
                        backup.execute("INSERT OR IGNORE INTO privacy_opt_outs (twitch_user_id) VALUES (?)", (user_id,))
                    for user_id in withdrawn:
                        backup.execute("DELETE FROM privacy_opt_outs WHERE twitch_user_id=?", (user_id,))
                    personal_tables = {"users", "ai_memory_entries", "leaderboard_counts"} & _tables(backup).keys()
                    for user_id in set(suppressed) | set(deleted):
                        for table in personal_tables:
                            backup.execute(f'DELETE FROM "{table}" WHERE twitch_user_id=?', (user_id,))
                _check_integrity(backup)
                metadata["recovery_counts"] = _snapshot(backup)[0]
            # Original source checksum/counts remain historical verification evidence.
            metadata["sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
            staged = manifest.with_suffix("." + secrets.token_hex(8) + ".tmp")
            try:
                _private_json(staged, metadata)
                os.replace(staged, manifest)
            finally:
                staged.unlink(missing_ok=True)
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
        raise DatabaseMigrationError("migrations.private_recovery_expiry_deletion_failed_review_recovery_copies_before") from None
