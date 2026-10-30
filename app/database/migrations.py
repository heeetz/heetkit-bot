"""Versioned SQLite upgrade and private recovery copies (standard library only).

Called before any async database work, under the application's exclusive guard.
No selected-channel inference, profile discovery, credentials or provider access.
"""

from __future__ import annotations

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

SCHEMA_VERSION = 2
RECOVERY_DAYS = 7
TABLE_COLUMNS = {
    "users": ("id", "channel_id", "twitch_user_id", "username", "created_at", "last_seen_at"),
    "ai_memory_entries": ("id", "channel_id", "twitch_user_id", "request_text", "response_text", "created_at"),
    "privacy_opt_outs": ("twitch_user_id", "username", "opted_out_at"),
    "schema_metadata": ("name", "value"),
}
SCHEMA_SQL = (
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


class DatabaseMigrationError(RuntimeError):
    """Fixed diagnostics only: sqlite exception strings may contain private values."""

    @property
    def operator_message(self):
        return (f"{self} Close every HeetKit process using this profile before retrying. "
                "Keep the database and recovery copies; do not delete them to bypass this error. "
                "See Data and privacy: Versioned database upgrade and recovery.")


class LegacyChannelMappingRequired(DatabaseMigrationError):
    """Only absent input for recognized unscoped legacy rows opens the Desktop form."""

    def __init__(self):
        super().__init__("Legacy history needs an explicit channel choice. Confirm its numeric Twitch channel ID in Desktop, "
                         "or provide legacy-channel-mapping.json beside the database for Server.")


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
        raise DatabaseMigrationError("Database integrity verification failed; startup stopped.")
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise DatabaseMigrationError("Database relationship verification failed; startup stopped.")


def _snapshot(connection):
    tables = _tables(connection)
    counts = {}
    digest = hashlib.sha256()
    for table in sorted(tables):
        if table not in TABLE_COLUMNS:
            raise DatabaseMigrationError("Unsupported database tables; startup stopped.")
        rows = connection.execute(f'SELECT * FROM "{table}" ORDER BY 1').fetchall()
        counts[table] = len(rows)
        digest.update(json.dumps([table, tables[table], rows], ensure_ascii=True).encode())
    return counts, digest.hexdigest()


def _private_json(path, payload):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as stream:
        json.dump(payload, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())


def _recovery_paths(path, version=0):
    folder = path.parent / (path.name + ".recovery")
    if folder.is_symlink() or folder.is_junction() or (folder.exists() and folder.resolve() != folder.absolute()):
        raise DatabaseMigrationError("Unsafe database recovery directory; startup stopped.")
    return folder, folder / f"schema-{version}.sqlite3", folder / f"schema-{version}.json"


def _backup(path, connection, now, version=0):
    maintain_recovery(path, now=now)
    folder, target, manifest = _recovery_paths(path, version)
    folder.mkdir(mode=0o700, exist_ok=True)
    if target.is_symlink() or manifest.is_symlink():
        raise DatabaseMigrationError("Unsafe database recovery file; startup stopped.")
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
            raise DatabaseMigrationError("Existing recovery snapshot cannot be verified; preserve it and resolve recovery before retrying.") from None
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
                    raise DatabaseMigrationError("Recovery snapshot counts/checksum verification failed.")
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


def _identifier(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9]{1,32}", value) is not None


def _mapping(path):
    try:
        payload = json.loads((path.parent / "legacy-channel-mapping.json").read_text(encoding="utf-8"))
        if type(payload.get("version")) is not int or payload["version"] != 1 or not _identifier(payload.get("channel_id")):
            raise ValueError
        return payload["channel_id"]
    except FileNotFoundError:
        raise LegacyChannelMappingRequired() from None
    except (OSError, ValueError, AttributeError):
        raise DatabaseMigrationError("Cannot read a valid legacy-channel-mapping.json (version 1, numeric channel_id). "
                                     "Correct the existing profile-local mapping or its permissions, then restart.") from None


def validate_legacy_channel_choice(channel_id, confirmed):
    if confirmed is not True:
        raise ValueError("Confirm that all unscoped legacy history belongs to the chosen channel.")
    if not _identifier(channel_id):
        raise ValueError("Enter the numeric Twitch channel ID (1–32 ASCII digits), verified separately with Twitch.")


def save_legacy_channel_mapping(path: Path, channel_id: str):
    """Caller holds the database guard. Create once; never replace existing input."""
    validate_legacy_channel_choice(channel_id, True)
    target = path.resolve().parent / "legacy-channel-mapping.json"
    staged = target.with_name(".legacy-channel-mapping-" + secrets.token_hex(8) + ".tmp")
    try:
        _private_json(staged, {"version": 1, "channel_id": channel_id})
        # Atomic create-if-absent on the same filesystem; unlike replace this
        # cannot overwrite a mapping supplied while the form was open.
        os.link(staged, target)
    except FileExistsError:
        raise DatabaseMigrationError("A legacy channel mapping already exists. Review it with HeetKit stopped, then restart; it was not overwritten.") from None
    except OSError:
        raise DatabaseMigrationError("Could not save the legacy channel choice. Check write permissions beside the profile database, then restart.") from None
    finally:
        try:
            staged.unlink(missing_ok=True)
        except OSError:
            pass


def _validate_current(connection):
    if _tables(connection) != TABLE_COLUMNS:
        raise DatabaseMigrationError("Unsupported database schema; startup stopped.")
    for table in TABLE_COLUMNS:
        definition = connection.execute(f'PRAGMA table_info("{table}")').fetchall()
        expected_types = {"id": "INTEGER", "channel_id": "VARCHAR(32)", "twitch_user_id": "VARCHAR(32)",
                          "username": "VARCHAR(64)", "request_text": "VARCHAR(500)", "response_text": "VARCHAR(500)",
                          "created_at": "DATETIME", "last_seen_at": "DATETIME", "opted_out_at": "DATETIME", "name": "TEXT", "value": "TEXT"}
        optional = {"username", "opted_out_at"} if table == "privacy_opt_outs" else set()
        if (any((not column[3] and column[1] not in optional) or column[2].upper() != expected_types[column[1]] for column in definition)
                or [column[1] for column in definition if column[5]] != [definition[0][1]]):
            raise DatabaseMigrationError("Invalid database field constraints; startup stopped.")
    if connection.execute("SELECT COUNT(*) FROM sqlite_master WHERE type IN ('trigger','view')").fetchone()[0]:
        raise DatabaseMigrationError("Unsupported database objects; startup stopped.")
    # Verify required identity uniqueness, not just matching column names.
    indexes = connection.execute("PRAGMA index_list(users)").fetchall()
    unique_keys = {tuple(row[2] for row in connection.execute(f'PRAGMA index_info("{index[1]}")'))
                   for index in indexes if index[2]}
    if ("channel_id", "twitch_user_id") not in unique_keys or ("twitch_user_id",) in unique_keys:
        raise DatabaseMigrationError("Invalid channel identity constraints; startup stopped.")
    marker = connection.execute("SELECT value FROM schema_metadata WHERE name='schema_version'").fetchone()
    if marker != (str(SCHEMA_VERSION),):
        raise DatabaseMigrationError("Database completion marker is missing; startup stopped.")


def _create(connection):
    for statement in SCHEMA_SQL:
        connection.execute(statement)
    connection.execute("INSERT INTO schema_metadata VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def _upgrade(connection, path, tables, stored_limit, now):
    rows = {}
    for name in ("users", "ai_memory_entries"):
        rows[name] = [dict(zip(tables[name], row)) for row in connection.execute(f'SELECT * FROM "{name}"')]
    suppressed = {row[0] for row in connection.execute("SELECT twitch_user_id FROM privacy_opt_outs")} if "privacy_opt_outs" in tables else set()
    if any(not _identifier(value) for value in suppressed):
        raise DatabaseMigrationError("Malformed legacy suppression record; startup stopped.")
    mapping = _mapping(path) if any(not row.get("channel_id") for values in rows.values() for row in values) else None
    report = {}
    kept = {}
    for name, values in rows.items():
        counts = dict(source=len(values), retained=0, opted_out=0, expired=0, count_cap=0)
        candidates = []
        identities = set()
        for row in values:
            channel = row.get("channel_id") or mapping
            if not _identifier(row["twitch_user_id"]) or not _identifier(channel) or type(row["id"]) is not int:
                raise DatabaseMigrationError("Malformed legacy identity; startup stopped.")
            row["channel_id"] = channel
            try:
                created = _date(row["created_at"])
                observed = _date(row["last_seen_at"]) if name == "users" else created
                if name == "users" and observed < created:
                    raise ValueError
                row["created_at"] = created.replace(tzinfo=None).isoformat(" ")
                if name == "users":
                    row["last_seen_at"] = observed.replace(tzinfo=None).isoformat(" ")
                fields = ("username",) if name == "users" else ("request_text", "response_text")
                if any(not isinstance(row[field], str) or not row[field] or len(row[field]) > (64 if field == "username" else 500) for field in fields):
                    raise ValueError
            except (TypeError, ValueError):
                raise DatabaseMigrationError("Malformed legacy personal row; startup stopped.") from None
            identity = (channel, row["twitch_user_id"]) if name == "users" else row["id"]
            if identity in identities:
                raise DatabaseMigrationError("Duplicate legacy identity; startup stopped.")
            identities.add(identity)
            if row["twitch_user_id"] in suppressed:
                counts["opted_out"] += 1
            elif observed <= now - timedelta(days=60):
                counts["expired"] += 1
            else:
                candidates.append(row)
        if name == "ai_memory_entries":
            groups = {}
            retained = []
            for row in sorted(candidates, key=lambda row: (_date(row["created_at"]), row["id"]), reverse=True):
                key = (row["channel_id"], row["twitch_user_id"])
                groups[key] = groups.get(key, 0) + 1
                if groups[key] <= stored_limit:
                    retained.append(row)
                else:
                    counts["count_cap"] += 1
            candidates = retained
        counts["retained"] = len(candidates)
        if counts["source"] != sum(counts[key] for key in ("retained", "opted_out", "expired", "count_cap")):
            raise DatabaseMigrationError("Legacy row reconciliation failed.")
        report[name] = counts
        kept[name] = candidates
    _backup(path, connection, now)
    for table in tables:
        connection.execute(f'DROP TABLE "{table}"')
    _create(connection)
    connection.executemany("INSERT INTO privacy_opt_outs (twitch_user_id) VALUES (?)", [(value,) for value in sorted(suppressed)])
    for name, values in kept.items():
        columns = TABLE_COLUMNS[name]
        expected = sorted(tuple(row[column] for column in columns) for row in values)
        connection.executemany(f'INSERT INTO "{name}" VALUES ({",".join("?" for _ in columns)})', expected)
        if sorted(connection.execute(f'SELECT * FROM "{name}"').fetchall()) != expected:
            raise DatabaseMigrationError("Migrated field preservation verification failed.")
    if {row[0] for row in connection.execute("SELECT twitch_user_id FROM privacy_opt_outs")} != suppressed:
        raise DatabaseMigrationError("Migrated suppression verification failed.")
    connection.execute("INSERT INTO schema_metadata VALUES ('legacy_migration', ?)",
                       (json.dumps({"channel_id": mapping, "completed_at": now.isoformat(), "counts": report}),))
    return report


def initialize_schema(path: Path, stored_limit: int, *, now=None, before_commit=None):
    """All DDL/data/version changes share an explicit, tested SQLite transaction."""
    path = path.resolve()
    now = now or datetime.now(timezone.utc)
    try:
        with closing(sqlite3.connect(path, timeout=0, isolation_level=None)) as connection:
            connection.execute("PRAGMA secure_delete=ON")
            connection.execute("BEGIN IMMEDIATE")
            try:
                _check_integrity(connection)
                tables = _tables(connection)
                if connection.execute("SELECT COUNT(*) FROM sqlite_master WHERE type IN ('trigger','view')").fetchone()[0]:
                    raise DatabaseMigrationError("Unsupported database objects; startup stopped.")
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                report = None
                if version == SCHEMA_VERSION:
                    _validate_current(connection)
                elif version == 1:
                    expected = {**TABLE_COLUMNS, "privacy_opt_outs": ("twitch_user_id",)}
                    if tables != expected or connection.execute("SELECT value FROM schema_metadata WHERE name='schema_version'").fetchone() != ('1',):
                        raise DatabaseMigrationError("Unsupported version-1 database schema; startup stopped.")
                    _backup(path, connection, now, version=1)
                    connection.execute("ALTER TABLE privacy_opt_outs ADD COLUMN username VARCHAR(64)")
                    connection.execute("ALTER TABLE privacy_opt_outs ADD COLUMN opted_out_at DATETIME")
                    connection.execute("UPDATE schema_metadata SET value=? WHERE name='schema_version'", (str(SCHEMA_VERSION),))
                    connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                    report = {"opt_out_metadata": "upgraded; historical names and dates remain unknown"}
                elif version != 0:
                    raise DatabaseMigrationError("Unsupported database version; use a compatible application.")
                elif not tables:
                    _create(connection)
                else:
                    if set(tables) - {"users", "ai_memory_entries", "privacy_opt_outs"} or not {"users", "ai_memory_entries"} <= tables.keys():
                        raise DatabaseMigrationError("Unrecognized legacy database; startup stopped.")
                    for name, columns in tables.items():
                        expected = ("twitch_user_id",) if name == "privacy_opt_outs" else TABLE_COLUMNS[name]
                        if set(columns) not in (set(expected), set(expected) - {"channel_id"}):
                            raise DatabaseMigrationError("Unrecognized legacy columns; startup stopped.")
                    report = _upgrade(connection, path, tables, stored_limit, now)
                _validate_current(connection)
                _check_integrity(connection)
                if before_commit is not None:
                    before_commit(connection)
                connection.commit()
                return report
            except BaseException:
                connection.rollback()
                raise
    except DatabaseMigrationError:
        raise
    except (sqlite3.Error, OSError, ValueError, TypeError):
        raise DatabaseMigrationError("Database initialization/backup failed; startup stopped with existing data preserved.") from None


def maintain_recovery(path: Path, suppressed=(), *, deleted=(), withdrawn=(), now=None):
    for version in (0, 1):
        _maintain_recovery(path, suppressed, deleted=deleted, withdrawn=withdrawn, now=now, version=version)


def _maintain_recovery(path: Path, suppressed=(), *, deleted=(), withdrawn=(), now=None, version=0):
    """Expire only our fixed recovery files; scrub known deletions before restore."""
    now = now or datetime.now(timezone.utc)
    folder, target, manifest = _recovery_paths(path.resolve(), version)
    if not target.exists() and not manifest.exists():
        return
    if target.is_symlink() or manifest.is_symlink():
        raise DatabaseMigrationError("Unsafe database recovery file.")
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
                    for user_id in set(suppressed) | set(deleted):
                        for table in ("users", "ai_memory_entries"):
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
        raise DatabaseMigrationError("Private recovery expiry/deletion failed; review recovery copies before restoring.") from None
