"""Offline operator tool for an identity-verified local privacy request.

Quit HeetKit (including tray Exit) before use. No profile discovery, provider
requests or database/backup creation are performed by this tool. Existing migration
recovery copies receive the same privacy request under their original expiry.
"""

import argparse
from datetime import datetime, timezone
from contextlib import closing
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.database.migrations import maintain_recovery
from app.database.migrations import SCHEMA_VERSION, DatabaseMigrationError
from app.desktop_instance import desktop_instance_guard, DesktopAlreadyRunningError


def apply_request(database_path: Path, user_id: str, action: str) -> None:
    if not user_id.isascii() or not user_id.isdigit() or not 1 <= len(user_id) <= 32:
        raise ValueError("Use the verified numeric Twitch account ID (1-32 digits).")
    if action not in {"delete", "opt-out", "opt-in"}:
        raise ValueError("Unknown privacy action.")
    # mode=rw refuses a misspelled/missing database instead of making a new one.
    uri = database_path.resolve().as_uri() + "?mode=rw"
    with desktop_instance_guard(database_path, database=True), closing(sqlite3.connect(uri, uri=True, timeout=0)) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"users", "ai_memory_entries", "privacy_opt_outs"} <= tables:
            raise ValueError("Expected an initialized HeetKit privacy-enabled database.")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1, SCHEMA_VERSION):
            raise ValueError("Use a privacy tool compatible with this database version.")
        connection.execute("PRAGMA secure_delete = ON")
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            if action == "opt-in":
                connection.execute("DELETE FROM privacy_opt_outs WHERE twitch_user_id = ?", (user_id,))
            elif action == "opt-out":
                if version >= 2:
                    connection.execute("INSERT OR IGNORE INTO privacy_opt_outs (twitch_user_id, opted_out_at) VALUES (?, ?)",
                        (user_id, datetime.now(timezone.utc).replace(tzinfo=None).isoformat(" ")))
                else:
                    connection.execute("INSERT OR IGNORE INTO privacy_opt_outs (twitch_user_id) VALUES (?)", (user_id,))
            if action != "opt-in":
                connection.execute("DELETE FROM ai_memory_entries WHERE twitch_user_id = ?", (user_id,))
                connection.execute("DELETE FROM users WHERE twitch_user_id = ?", (user_id,))
        maintain_recovery(database_path, (user_id,) if action == "opt-out" else (),
                          deleted=(user_id,) if action == "delete" else (),
                          withdrawn=(user_id,) if action == "opt-in" else ())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True, help="Explicit existing database path.")
    parser.add_argument("--user-id", required=True, help="Identity-verified numeric Twitch ID.")
    parser.add_argument("--action", choices=("delete", "opt-out", "opt-in"), required=True)
    args = parser.parse_args()
    try:
        apply_request(args.database, args.user_id, args.action)
    except (ValueError, sqlite3.Error, DatabaseMigrationError, DesktopAlreadyRunningError, OSError) as error:
        # Database exceptions can contain private paths or values.
        parser.exit(1, f"Privacy request failed ({type(error).__name__}); check the path, schema and stopped application.\n")
    print("Local privacy request applied. Review backups, logs and provider data separately.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
