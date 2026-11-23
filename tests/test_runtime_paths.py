"""Focused migration and reset behavior for the platform runtime root."""

import json
from pathlib import Path

from sqlalchemy.engine import make_url

from app.app_settings import AppSettingsStore
from app.config_file import LEGACY_FILES, ConfigFile
from app.custom_commands import CustomCommandStore
from app.runtime_paths import RuntimePaths, prepare_runtime_data
from app.runtime_state import RuntimeState


def test_missing_files_create_directories_and_seed_filter_defaults(tmp_path: Path) -> None:
    legacy = tmp_path / "checkout" / "data"
    (legacy / "filters").mkdir(parents=True)
    (legacy / "filters" / "blocked_patterns.txt").write_text("safe-pattern\n", encoding="utf-8")
    paths = RuntimePaths(tmp_path / "appdata")

    token_file, database_url = prepare_runtime_data(
        f"sqlite+aiosqlite:///{legacy / 'missing.db'}",
        paths=paths,
    )

    assert all(directory.is_dir() for directory in (paths.config, paths.data, paths.auth, paths.cache))
    assert set(json.loads(paths.config_file.read_text(encoding="utf-8"))) == {"schema_version", "triggers"}
    assert not paths.database.exists()
    assert not paths.tokens.exists()
    assert token_file == str(paths.tokens)
    assert make_url(database_url).database == str(paths.database)
    (paths.filters / "blocked_patterns.txt").unlink()
    prepare_runtime_data(database_url, paths=paths)
    assert "safe-pattern" not in (paths.filters / "blocked_patterns.txt").read_text(encoding="utf-8")


def test_initialization_preserves_existing_profile_bytes(tmp_path: Path) -> None:
    legacy = tmp_path / "checkout" / "data"
    legacy.mkdir(parents=True)
    paths = RuntimePaths(tmp_path / "profile")
    paths.config.mkdir(parents=True)
    paths.auth.mkdir()
    paths.data.mkdir()
    # Include unsupported/malformed files: initialization must preserve them,
    # even when their readers would currently fall back to neutral defaults.
    files = {
        paths.config_file: b"unreadable current settings",
        paths.tokens: b"current synthetic token",
        paths.database: b"current database must not be opened by migration",
    }
    for destination, content in files.items():
        destination.write_bytes(content)
        (legacy / destination.name).write_bytes(b"obsolete checkout data")
    for _ in range(2):
        prepare_runtime_data(f"sqlite+aiosqlite:///{legacy / 'storage.db'}", paths=paths)
        assert all(path.read_bytes() == content for path, content in files.items())


def test_1_6_profile_moves_into_config_json_once_with_complete_backup(tmp_path: Path) -> None:
    paths = RuntimePaths(tmp_path / "profile")
    paths.config.mkdir(parents=True)
    command = {"id": "d309228e-92a3-422a-8284-70f52c41cce7", "name": "hello", "enabled": True,
               "responses": ["Привіт"], "permission": "USER", "per_user_seconds": 0, "global_seconds": 0, "aliases": []}
    legacy = {
        "app_settings.json": {"version": 1, "startup": {"operation_mode": "manual"}, "interface": {"language": "uk"}},
        "command_settings.json": {"ping": {"enabled": False}, "future": {"keep": True}},
        "custom_commands.json": {"version": 2, "commands": [command]},
        "message_triggers.json": {"version": 1, "triggers": []},
        "personality_settings.json": {"active_personality": "local", "overrides": {"local": "Keep my style"}},
        "announcements.json": {"version": 1, "announcements": []},
    }
    originals = {name: json.dumps(payload, ensure_ascii=False).encode("utf-8") for name, payload in legacy.items()}
    originals["custom_commands.json"] = b"\xef\xbb\xbf" + originals["custom_commands.json"]  # Windows editor BOM
    originals["fun_settings.json"] = b'{"version":1,"fates":["unfinished'
    people = paths.config / "ai_user_blocks.json"
    people.write_bytes(b'{"version":1,"users":[]}')
    for name, data in originals.items():
        (paths.config / name).write_bytes(data)

    prepare_runtime_data("sqlite+aiosqlite:///:memory:", paths=paths)

    backup = paths.config / "backup-1.6"
    assert {path.name: path.read_bytes() for path in backup.iterdir()} == originals
    assert not any((paths.config / name).exists() for name in originals)
    assert people.read_bytes() == b'{"version":1,"users":[]}'
    document = json.loads(paths.config_file.read_text(encoding="utf-8"))
    assert document == {"schema_version": 1, **{section: legacy[name] for section, name in LEGACY_FILES.items()
                                                if name in legacy}}  # The unreadable file stays in the backup only.
    config = ConfigFile(paths.config_file)
    assert AppSettingsStore(config).snapshot().interface.language == "uk"
    assert CustomCommandStore(config, set()).get_by_name("hello").responses == ("Привіт",)
    assert RuntimeState(config).active_ai_personality == "local"

    migrated = paths.config_file.read_bytes()
    prepare_runtime_data("sqlite+aiosqlite:///:memory:", paths=paths)
    assert paths.config_file.read_bytes() == migrated
    assert list(paths.config.glob("backup-1.6*")) == [backup]
