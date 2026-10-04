"""Focused migration and reset behavior for the platform runtime root."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

from app.fun_settings import FunSettingsStore
from app.runtime_paths import RuntimeDataError, RuntimePaths, prepare_runtime_data
from app.runtime_state import RuntimeState


def test_migrates_existing_state_once_and_preserves_sqlite_rows(tmp_path: Path) -> None:
    legacy = tmp_path / "checkout" / "data"
    legacy.mkdir(parents=True)
    (legacy / "filters").mkdir()
    (legacy / "app_settings.json").write_text('{"version": 1}', encoding="utf-8")
    (legacy / "command_settings.json").write_text('{"version": 1}', encoding="utf-8")
    (legacy / "personality_settings.json").write_text('{"version": 1}', encoding="utf-8")
    (legacy / "custom_commands.json").write_text('{"version": 1, "commands": []}', encoding="utf-8")
    (legacy / "message_triggers.json").write_text('{"version": 1, "triggers": []}', encoding="utf-8")
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
        migrate_legacy=True,
    )

    assert token_file == str(paths.tokens)
    assert make_url(database_url).database == str(paths.database)
    assert paths.app_settings.read_text(encoding="utf-8") == '{"version": 1}'
    assert paths.command_settings.exists()
    assert paths.personality_settings.exists()
    assert paths.custom_commands.read_bytes() == (legacy / "custom_commands.json").read_bytes()
    assert paths.message_triggers.read_bytes() == (legacy / "message_triggers.json").read_bytes()
    assert paths.tokens.read_text(encoding="utf-8") == "private-token"
    assert (paths.filters / "blocked_words.txt").read_text(encoding="utf-8") == "legacy rule\n"
    with closing(sqlite3.connect(paths.database)) as connection:
        assert connection.execute("SELECT value FROM remembered").fetchone() == ("preserved",)
    assert old_db.exists()

    paths.app_settings.unlink()
    paths.tokens.write_text("current-token", encoding="utf-8")
    prepare_runtime_data(str(old_db), f"sqlite+aiosqlite:///{old_db}", paths=paths, legacy_data=legacy, migrate_legacy=True)
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
        migrate_legacy=True,
    )

    assert all(directory.is_dir() for directory in (paths.config, paths.data, paths.auth, paths.cache))
    assert not paths.app_settings.exists()
    assert not paths.database.exists()
    assert not paths.tokens.exists()
    assert token_file == str(paths.tokens)
    assert make_url(database_url).database == str(paths.database)
    (paths.filters / "blocked_patterns.txt").unlink()
    prepare_runtime_data(token_file, database_url, paths=paths, legacy_data=legacy)
    assert "safe-pattern" not in (paths.filters / "blocked_patterns.txt").read_text(encoding="utf-8")


def test_legacy_personalities_and_fun_responses_survive_migration_and_restart(tmp_path: Path) -> None:
    legacy = tmp_path / "checkout" / "data"
    legacy.mkdir(parents=True)
    personalities = {
        "active_personality": "retired-style",
        "overrides": {"retired-style": "Local style: café, привет, {literal braces}"},
    }
    fun = {"version": 1, "tg_message": "Local community link",
           "forecasts": ["Local forecast, with punctuation", "A second response"],
           "extra": {"keep": True}}
    for filename, payload in (("personality_settings.json", personalities), ("fun_settings.json", fun)):
        (legacy / filename).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    paths = RuntimePaths(tmp_path / "profile")
    prepare_runtime_data("tokens.json", "sqlite+aiosqlite:///missing.db",
                         paths=paths, legacy_data=legacy, migrate_legacy=True)
    original = {path: path.read_bytes() for path in (
        paths.personality_settings, paths.config / "fun_settings.json", paths.migration_marker,
    )}

    state = RuntimeState(personality_settings_path=paths.personality_settings)
    assert state.available_personalities == ("neutral", "retired-style")
    assert state.active_ai_personality == personalities["active_personality"]
    assert state.get_ai_personality_prompt("retired-style") == personalities["overrides"]["retired-style"]
    store = FunSettingsStore(paths.config / "fun_settings.json")
    assert store.forecasts == tuple(fun["forecasts"])
    assert store.tg_message == fun["tg_message"]
    assert paths.personality_settings.read_bytes() == (legacy / "personality_settings.json").read_bytes()
    assert store.path.read_bytes() == (legacy / "fun_settings.json").read_bytes()

    # A later checkout/reset cannot replace the already migrated local snapshot.
    for filename in ("personality_settings.json", "fun_settings.json"):
        (legacy / filename).write_text("{}", encoding="utf-8")
    prepare_runtime_data("tokens.json", "sqlite+aiosqlite:///missing.db",
                         paths=paths, legacy_data=legacy, migrate_legacy=True)
    assert all(path.read_bytes() == content for path, content in original.items())
    assert RuntimeState(personality_settings_path=paths.personality_settings).active_ai_personality == "retired-style"
    assert FunSettingsStore(store.path).forecasts == tuple(fun["forecasts"])


@pytest.mark.parametrize("migration_completed", [False, True])
def test_initialization_preserves_existing_profile_bytes(tmp_path: Path, migration_completed: bool) -> None:
    legacy = tmp_path / "checkout" / "data"
    legacy.mkdir(parents=True)
    paths = RuntimePaths(tmp_path / "profile")
    paths.config.mkdir(parents=True)
    paths.auth.mkdir()
    paths.data.mkdir()
    # Include unsupported/malformed files: initialization must preserve them,
    # even when their readers would currently fall back to neutral defaults.
    files = {
        paths.personality_settings: b'{"active_personality":"local","overrides":{"local":"Keep my style"}}',
        paths.config / "fun_settings.json": b'{"version":99,"forecasts":["Future response"]}',
        paths.app_settings: b"unreadable current settings",
        paths.command_settings: b"current command settings",
        paths.custom_commands: b"current custom commands",
        paths.tokens: b"current synthetic token",
        paths.database: b"current database must not be opened by migration",
    }
    for destination, content in files.items():
        destination.write_bytes(content)
        (legacy / destination.name).write_bytes(b"obsolete checkout data")
    if migration_completed:
        paths.migration_marker.write_bytes(b"existing marker")
        files[paths.migration_marker] = b"existing marker"

    for _ in range(2):
        prepare_runtime_data(str(legacy / "twitchio_tokens.json"),
                             f"sqlite+aiosqlite:///{legacy / 'twitch_bot.db'}",
                             paths=paths, legacy_data=legacy, migrate_legacy=True)
        assert all(path.read_bytes() == content for path, content in files.items())


def test_interrupted_migration_retries_without_replacing_recovered_files(tmp_path: Path, monkeypatch) -> None:
    from app import runtime_paths

    legacy = tmp_path / "checkout" / "data"
    legacy.mkdir(parents=True)
    for filename in ("personality_settings.json", "fun_settings.json"):
        (legacy / filename).write_bytes(b'{"local":"preserve exact bytes"}')
    paths = RuntimePaths(tmp_path / "profile")
    copy_if_missing = runtime_paths._copy_if_missing

    def fail_fun_copy(source, destination, **kwargs):
        if destination == paths.config / "fun_settings.json":
            raise OSError("synthetic copy failure")
        return copy_if_missing(source, destination, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(runtime_paths, "_copy_if_missing", fail_fun_copy)
        with pytest.raises(RuntimeDataError):
            prepare_runtime_data("tokens.json", "sqlite+aiosqlite:///missing.db",
                                 paths=paths, legacy_data=legacy, migrate_legacy=True)
    assert not paths.migration_marker.exists()
    assert not (paths.config / "fun_settings.json").exists()
    recovered = paths.personality_settings.read_bytes()
    (legacy / "personality_settings.json").write_bytes(b"changed legacy content")

    prepare_runtime_data("tokens.json", "sqlite+aiosqlite:///missing.db",
                         paths=paths, legacy_data=legacy, migrate_legacy=True)
    assert paths.migration_marker.exists()
    assert paths.personality_settings.read_bytes() == recovered
    assert (paths.config / "fun_settings.json").read_bytes() == (legacy / "fun_settings.json").read_bytes()
