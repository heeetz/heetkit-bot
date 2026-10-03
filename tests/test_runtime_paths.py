"""Focused migration and reset behavior for the platform runtime root."""

import sqlite3
from contextlib import closing
from pathlib import Path

from sqlalchemy.engine import make_url

from app.runtime_paths import RuntimePaths, prepare_runtime_data


def test_migrates_existing_state_once_and_preserves_sqlite_rows(tmp_path: Path) -> None:
    legacy = tmp_path / "checkout" / "data"
    legacy.mkdir(parents=True)
    (legacy / "filters").mkdir()
    (legacy / "app_settings.json").write_text('{"version": 1}', encoding="utf-8")
    (legacy / "command_settings.json").write_text('{"version": 1}', encoding="utf-8")
    (legacy / "personality_settings.json").write_text('{"version": 1}', encoding="utf-8")
    (legacy / "filters" / "blocked_words.txt").write_text("legacy rule\n", encoding="utf-8")
    (legacy / "twitchio_tokens.json").write_text("private-token", encoding="utf-8")
    old_db = legacy / "twitch_bot.db"
    with closing(sqlite3.connect(old_db)) as connection:
        connection.execute("CREATE TABLE remembered (value TEXT)")
        connection.execute("INSERT INTO remembered VALUES ('preserved')")
        connection.commit()

    paths = RuntimePaths(tmp_path / "appdata")
    token_file, database_url = prepare_runtime_data(
        str(legacy / "twitchio_tokens.json"),
        f"sqlite+aiosqlite:///{old_db}",
        paths=paths,
        legacy_data=legacy,
    )

    assert token_file == str(paths.tokens)
    assert make_url(database_url).database == str(paths.database)
    assert paths.app_settings.read_text(encoding="utf-8") == '{"version": 1}'
    assert paths.command_settings.exists()
    assert paths.personality_settings.exists()
    assert paths.tokens.read_text(encoding="utf-8") == "private-token"
    assert (paths.filters / "blocked_words.txt").read_text(encoding="utf-8") == "legacy rule\n"
    with closing(sqlite3.connect(paths.database)) as connection:
        assert connection.execute("SELECT value FROM remembered").fetchone() == ("preserved",)
    assert old_db.exists()

    paths.app_settings.unlink()
    paths.tokens.write_text("current-token", encoding="utf-8")
    prepare_runtime_data(str(old_db), f"sqlite+aiosqlite:///{old_db}", paths=paths, legacy_data=legacy)
    assert not paths.app_settings.exists()
    assert paths.tokens.read_text(encoding="utf-8") == "current-token"


def test_missing_files_create_directories_and_seed_filter_defaults(tmp_path: Path) -> None:
    legacy = tmp_path / "checkout" / "data"
    (legacy / "filters").mkdir(parents=True)
    (legacy / "filters" / "blocked_patterns.txt").write_text("safe-pattern\n", encoding="utf-8")
    paths = RuntimePaths(tmp_path / "appdata")

    token_file, database_url = prepare_runtime_data(
        str(legacy / "missing-tokens.json"),
        f"sqlite+aiosqlite:///{legacy / 'missing.db'}",
        paths=paths,
        legacy_data=legacy,
    )

    assert all(directory.is_dir() for directory in (paths.config, paths.data, paths.auth, paths.cache))
    assert not paths.app_settings.exists()
    assert not paths.database.exists()
    assert not paths.tokens.exists()
    assert token_file == str(paths.tokens)
    assert make_url(database_url).database == str(paths.database)
    (paths.filters / "blocked_patterns.txt").unlink()
    prepare_runtime_data(token_file, database_url, paths=paths, legacy_data=legacy)
    assert (paths.filters / "blocked_patterns.txt").read_text(encoding="utf-8") == "safe-pattern\n"
