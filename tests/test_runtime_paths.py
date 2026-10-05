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


@pytest.fixture
def branded_roots(tmp_path, monkeypatch):
    from app import runtime_paths

    monkeypatch.delenv(runtime_paths.DATA_DIR_ENV, raising=False)
    monkeypatch.delenv(runtime_paths.LEGACY_DATA_DIR_ENV, raising=False)
    monkeypatch.setattr(runtime_paths, "user_data_path", lambda name, **kwargs: tmp_path / name)
    # Former name is intentional legacy compatibility input.
    former = tmp_path / runtime_paths.LEGACY_APP_NAME
    return former, RuntimePaths.default()


def test_brand_migration_copies_complete_profile_and_wal_once(branded_roots):
    former, paths = branded_roots
    assert paths.root.name == "HeetKit"
    files = {
        "config/personality_settings.json": b'{"active_personality":"custom","overrides":{"custom":"local style"},"profile_instructions":"local instructions"}',
        "config/app_settings.json": b'{"version":1,"twitch":{"channel":"local"}}',
        "config/fun_settings.json": b'{"version":1,"forecasts":["local forecast"]}',
        "config/custom_commands.json": b'{"version":1,"commands":[]}',
        "config/command_settings.json": b'{"ask":{"enabled":false}}',
        "config/filters/blocked_patterns.txt": b"private synthetic rule",
        "auth/twitchio_tokens.json": b"synthetic oauth state",
        "cache/extra/nested.bin": b"arbitrary profile cache",
        "other-profile-state.bin": b"unknown legitimate state",
        ".legacy-migration-v1": b"previous checkout migration",
    }
    for relative, content in files.items():
        target = former / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    old_database = former / "data" / "twitch_bot.db"  # Legacy database input.
    old_database.parent.mkdir()
    with closing(sqlite3.connect(old_database)) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE remembered (value TEXT)")
        connection.execute("INSERT INTO remembered VALUES ('wal row')")
        connection.commit()
        assert Path(str(old_database) + "-wal").exists()
        prepare_runtime_data("tokens.json", "sqlite+aiosqlite:///missing.db", paths=paths, legacy_data=None)
        with closing(sqlite3.connect(paths.database)) as migrated:
            assert migrated.execute("SELECT value FROM remembered").fetchone() == ("wal row",)
    assert paths.database.name == "heetkit.db"
    assert not (paths.data / "twitch_bot.db").exists()  # No newly created old-brand file.
    assert not Path(str(paths.database) + "-wal").exists()
    assert all((paths.root / relative).read_bytes() == content for relative, content in files.items())
    assert all((former / relative).read_bytes() == content for relative, content in files.items())
    assert paths.brand_migration_marker.exists()
    state = RuntimeState(personality_settings_path=paths.personality_settings)
    assert state.active_ai_personality == "custom"
    assert state.profile_instructions == "local instructions"
    paths.personality_settings.unlink()
    paths.database.unlink()
    prepare_runtime_data("tokens.json", "sqlite+aiosqlite:///missing.db", paths=paths, legacy_data=former)
    assert not paths.personality_settings.exists()
    assert not paths.database.exists()
    assert former.is_dir() and old_database.exists()


def test_brand_migration_preserves_authoritative_new_profile_and_recovers_missing_files(branded_roots):
    former, paths = branded_roots
    (former / "config").mkdir(parents=True)
    (former / "config" / "app_settings.json").write_bytes(b"old settings")
    (former / "extra.bin").write_bytes(b"missing state")
    paths.config.mkdir(parents=True)
    paths.app_settings.write_bytes(b"authoritative HeetKit settings")
    paths.data.mkdir()
    paths.database.write_bytes(b"authoritative database: never open for migration")
    prepare_runtime_data("tokens.json", "sqlite+aiosqlite:///missing.db", paths=paths, legacy_data=None)
    assert paths.app_settings.read_bytes() == b"authoritative HeetKit settings"
    assert paths.database.read_bytes() == b"authoritative database: never open for migration"
    assert (paths.root / "extra.bin").read_bytes() == b"missing state"
    (paths.root / "extra.bin").unlink()
    prepare_runtime_data("tokens.json", "sqlite+aiosqlite:///missing.db", paths=paths, legacy_data=None)
    assert not (paths.root / "extra.bin").exists()


def test_brand_migration_reports_conflict_without_completing_marker(branded_roots):
    former, paths = branded_roots
    (former / "config").mkdir(parents=True)
    paths.root.mkdir()
    paths.config.write_bytes(b"existing file")
    with pytest.raises(RuntimeDataError, match="file/directory conflict"):
        prepare_runtime_data("tokens.json", "sqlite+aiosqlite:///missing.db", paths=paths, legacy_data=None)
    assert paths.config.read_bytes() == b"existing file"
    assert not paths.brand_migration_marker.exists()


def test_brand_migration_rejects_links_without_following_them(branded_roots, monkeypatch):
    from app import runtime_paths

    former, paths = branded_roots
    former.mkdir()
    (former / "linked").mkdir()
    (former / "linked" / "private.bin").write_bytes(b"outside state")
    monkeypatch.setattr(runtime_paths, "_is_link", lambda path: path.name == "linked")
    with pytest.raises(RuntimeDataError, match="symbolic links or junctions"):
        prepare_runtime_data("tokens.json", "sqlite+aiosqlite:///missing.db", paths=paths, legacy_data=None)
    assert not (paths.root / "linked").exists()
    assert not paths.brand_migration_marker.exists()


def test_brand_migration_retries_failed_copy_without_overwriting(branded_roots, monkeypatch):
    from app import runtime_paths

    former, paths = branded_roots
    former.mkdir()
    (former / paths.brand_migration_marker.name).touch()
    (former / "a.bin").write_bytes(b"first copy")
    (former / "b.bin").write_bytes(b"second copy")
    original = runtime_paths._copy_if_missing

    def fail_second(source, destination, **kwargs):
        if source.name == "b.bin":
            raise OSError("synthetic copy failure")
        return original(source, destination, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(runtime_paths, "_copy_if_missing", fail_second)
        with pytest.raises(RuntimeDataError):
            prepare_runtime_data("tokens.json", "sqlite+aiosqlite:///missing.db", paths=paths, legacy_data=None)
    assert not paths.brand_migration_marker.exists()
    (paths.root / "a.bin").write_bytes(b"newer current data")
    prepare_runtime_data("tokens.json", "sqlite+aiosqlite:///missing.db", paths=paths, legacy_data=None)
    assert (paths.root / "a.bin").read_bytes() == b"newer current data"
    assert (paths.root / "b.bin").read_bytes() == b"second copy"


def test_explicit_old_named_profile_is_isolated_and_migrates_only_its_database(branded_roots, tmp_path):
    former, _ = branded_roots
    former.mkdir()
    (former / "owner.bin").write_bytes(b"must not import")
    paths = RuntimePaths(tmp_path / "explicit" / "TwitchBot")  # Arbitrary legacy-looking name.
    paths.data.mkdir(parents=True)
    old_database = paths.data / "twitch_bot.db"  # This profile's legacy database only.
    with closing(sqlite3.connect(old_database)) as connection:
        connection.execute("CREATE TABLE own (value TEXT)")
        connection.execute("INSERT INTO own VALUES ('explicit profile')")
        connection.commit()
    prepare_runtime_data("tokens.json", "sqlite+aiosqlite:///missing.db", paths=paths, legacy_data=former)
    assert not (paths.root / "owner.bin").exists()
    with closing(sqlite3.connect(paths.database)) as connection:
        assert connection.execute("SELECT value FROM own").fetchone() == ("explicit profile",)
    assert old_database.exists()
    paths.database.unlink()
    prepare_runtime_data("tokens.json", "sqlite+aiosqlite:///missing.db", paths=paths, legacy_data=former)
    assert not paths.database.exists()


def test_data_directory_environment_legacy_fallback_and_new_precedence(tmp_path, monkeypatch):
    from app.runtime_paths import DATA_DIR_ENV, LEGACY_DATA_DIR_ENV

    monkeypatch.delenv(DATA_DIR_ENV, raising=False)
    monkeypatch.setenv(LEGACY_DATA_DIR_ENV, str(tmp_path / "legacy-override"))
    assert RuntimePaths.default().root == (tmp_path / "legacy-override").resolve()
    monkeypatch.setenv(DATA_DIR_ENV, str(tmp_path / "canonical-override"))
    assert RuntimePaths.default().root == (tmp_path / "canonical-override").resolve()


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


def test_default_profile_marker_does_not_prove_optional_settings_were_recovered(tmp_path: Path, monkeypatch) -> None:
    from app import runtime_paths
    from app.fun_settings import FORECASTS

    paths = RuntimePaths(tmp_path / "default-profile")
    paths.config.mkdir(parents=True)
    paths.migration_marker.write_bytes(b"previous migration attempt")
    monkeypatch.delenv(runtime_paths.DATA_DIR_ENV, raising=False)
    monkeypatch.setattr(runtime_paths, "user_data_path", lambda *args, **kwargs: paths.root)
    assert RuntimePaths.default() == paths
    assert paths.is_default_profile

    legacy = tmp_path / "checkout" / "data"
    legacy.mkdir(parents=True)
    (legacy / "personality_settings.json").write_text(json.dumps({
        "active_personality": "archived-style",
        "overrides": {"archived-style": "An editable local style"},
    }), encoding="utf-8")
    (legacy / "fun_settings.json").write_text(json.dumps({
        "version": 1, "forecasts": ["An exact archived response"],
        "tg_message": "An archived community message",
    }), encoding="utf-8")

    # Even a real default profile skips old JSON once the marker exists.
    prepare_runtime_data("tokens.json", "sqlite+aiosqlite:///missing.db", legacy_data=legacy)
    assert not paths.personality_settings.exists()
    assert not (paths.config / "fun_settings.json").exists()
    assert RuntimeState(personality_settings_path=paths.personality_settings).available_personalities == ("neutral",)
    assert FunSettingsStore(paths.config / "fun_settings.json").forecasts == FORECASTS
    assert paths.migration_marker.read_bytes() == b"previous migration attempt"

    # Explicit private recovery restores only the selected profile; initialization
    # keeps those files instead of using shipped starters or repeating migration.
    recovered = {}
    for filename in ("personality_settings.json", "fun_settings.json"):
        destination = paths.config / filename
        recovered[destination] = (legacy / filename).read_bytes()
        destination.write_bytes(recovered[destination])
    prepare_runtime_data("tokens.json", "sqlite+aiosqlite:///missing.db", legacy_data=legacy)
    assert all(path.read_bytes() == raw for path, raw in recovered.items())
    state = RuntimeState(personality_settings_path=paths.personality_settings)
    assert state.available_personalities == ("neutral", "archived-style")
    assert state.active_ai_personality == "archived-style"
    assert state.get_ai_personality_prompt("archived-style") == "An editable local style"
    fun = FunSettingsStore(paths.config / "fun_settings.json")
    assert fun.forecasts == ("An exact archived response",)
    assert fun.tg_message == "An archived community message"
