"""Focused migration and reset behavior for the platform runtime root."""

from pathlib import Path

from sqlalchemy.engine import make_url

from app.runtime_paths import RuntimePaths, prepare_runtime_data


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
    assert not paths.app_settings.exists()
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
    for _ in range(2):
        prepare_runtime_data(f"sqlite+aiosqlite:///{legacy / 'storage.db'}", paths=paths)
        assert all(path.read_bytes() == content for path, content in files.items())
