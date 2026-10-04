"""One platform-owned home for mutable desktop data and legacy migration."""

from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_path
from sqlalchemy.engine import make_url


_PACKAGE_ROOT = Path(__file__).resolve().parent
_CANDIDATE_SOURCE_ROOT = _PACKAGE_ROOT.parent
SOURCE_ROOT: Path | None = (
    _CANDIDATE_SOURCE_ROOT
    if (_CANDIDATE_SOURCE_ROOT / "pyproject.toml").is_file()
    and (_CANDIDATE_SOURCE_ROOT / "frontend" / "package.json").is_file()
    else None
)
LEGACY_DATA: Path | None = SOURCE_ROOT / "data" if SOURCE_ROOT is not None else None
DEFAULT_TRIGGERS = _PACKAGE_ROOT / "resources" / "default_triggers.json"
DEFAULT_FILTERS = _PACKAGE_ROOT / "resources" / "filters"
PACKAGED_FRONTEND = _PACKAGE_ROOT / "resources" / "frontend" / "index.html"
DATA_DIR_ENV = "TWITCH_BOT_DATA_DIR"
FILTER_NAMES = ("blocked_words.txt", "blocked_phrases.txt", "blocked_patterns.txt")


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    root: Path

    @classmethod
    def default(cls) -> RuntimePaths:
        if override := os.environ.get(DATA_DIR_ENV):
            return cls(Path(override).expanduser().resolve())
        return cls(user_data_path("TwitchBot", appauthor=False))

    @property
    def is_default_profile(self) -> bool:
        return self.root.resolve() == user_data_path("TwitchBot", appauthor=False).resolve()

    @property
    def config(self) -> Path:
        return self.root / "config"

    @property
    def data(self) -> Path:
        return self.root / "data"

    @property
    def auth(self) -> Path:
        return self.root / "auth"

    @property
    def cache(self) -> Path:
        return self.root / "cache"

    @property
    def filters(self) -> Path:
        return self.config / "filters"

    @property
    def app_settings(self) -> Path:
        return self.config / "app_settings.json"

    @property
    def command_settings(self) -> Path:
        return self.config / "command_settings.json"

    @property
    def custom_commands(self) -> Path:
        return self.config / "custom_commands.json"

    @property
    def message_triggers(self) -> Path:
        return self.config / "message_triggers.json"

    @property
    def personality_settings(self) -> Path:
        return self.config / "personality_settings.json"

    @property
    def database(self) -> Path:
        return self.data / "twitch_bot.db"

    @property
    def tokens(self) -> Path:
        return self.auth / "twitchio_tokens.json"

    @property
    def migration_marker(self) -> Path:
        return self.root / ".legacy-migration-v1"


class RuntimeDataError(RuntimeError):
    """Existing local state could not be copied safely."""


def _copy_if_missing(source: Path, destination: Path, *, secret: bool = False) -> None:
    if destination.exists() or not source.is_file() or source.resolve() == destination.resolve():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as output:
            temporary = Path(output.name)
            with source.open("rb") as input_file:
                shutil.copyfileobj(input_file, output)
            output.flush()
            os.fsync(output.fileno())
        if secret:
            temporary.chmod(0o600)
        if not destination.exists():
            temporary.replace(destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _backup_sqlite_if_missing(source: Path, destination: Path) -> None:
    if destination.exists() or not source.is_file() or source.resolve() == destination.resolve():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, suffix=".db", delete=False) as output:
            temporary = Path(output.name)
        with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as old:
            with closing(sqlite3.connect(temporary)) as new:
                old.backup(new)
                new.commit()
        if not destination.exists():
            temporary.replace(destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _profile_relative_path(value: str | Path, paths: RuntimePaths) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path.resolve()
    base = SOURCE_ROOT if paths.is_default_profile and SOURCE_ROOT is not None else paths.root
    return (base / path).resolve()


def _sqlite_file(database_url: str, *, base_dir: Path) -> Path | None:
    url = make_url(database_url)
    if not url.drivername.startswith("sqlite") or not url.database or url.database == ":memory:":
        return None
    database = Path(url.database)
    return (database if database.is_absolute() else base_dir / database).resolve()


def prepare_runtime_data(
    token_file: str,
    database_url: str,
    *,
    paths: RuntimePaths | None = None,
    legacy_data: Path | None = LEGACY_DATA,
    migrate_legacy: bool | None = None,
) -> tuple[str, str]:
    """Copy legacy state once, then return canonical token and SQLite locations.

    Old files remain in place. The marker records the one-shot migration attempt,
    not the presence of every optional settings file. It prevents deleted settings
    from being restored from the old checkout on a later launch; missing user
    settings require explicit recovery from a backup. SQLite uses its backup API
    so WAL contents are included in the migration.
    """
    paths = paths or RuntimePaths.default()
    if migrate_legacy is None:
        migrate_legacy = paths.is_default_profile
    legacy_source = Path(legacy_data) if legacy_data is not None else None
    try:
        for directory in (paths.config, paths.data, paths.auth, paths.cache, paths.filters):
            directory.mkdir(parents=True, exist_ok=True)
        configured_database = _sqlite_file(
            database_url,
            base_dir=(SOURCE_ROOT if paths.is_default_profile and SOURCE_ROOT is not None else paths.root),
        )
        if not paths.migration_marker.exists():
            if migrate_legacy and legacy_source is not None:
                for filename, destination in (
                    ("app_settings.json", paths.app_settings),
                    ("command_settings.json", paths.command_settings),
                    ("personality_settings.json", paths.personality_settings),
                    ("custom_commands.json", paths.custom_commands),
                    ("message_triggers.json", paths.message_triggers),
                    ("fun_settings.json", paths.config / "fun_settings.json"),
                ):
                    _copy_if_missing(legacy_source / filename, destination)
                for filename in FILTER_NAMES:
                    _copy_if_missing(legacy_source / "filters" / filename, paths.filters / filename)

            if migrate_legacy and legacy_source is not None:
                configured_token = _profile_relative_path(token_file, paths)
                token_source = (
                    configured_token
                    if configured_token.is_file()
                    else legacy_source / "twitchio_tokens.json"
                )
                _copy_if_missing(token_source, paths.tokens, secret=True)

            if migrate_legacy and legacy_source is not None and configured_database is not None:
                database_source = (
                    configured_database
                    if configured_database.is_file()
                    else legacy_source / "twitch_bot.db"
                )
                _backup_sqlite_if_missing(database_source, paths.database)
            paths.migration_marker.touch()
        for filename in FILTER_NAMES:
            _copy_if_missing(DEFAULT_FILTERS / filename, paths.filters / filename)
        _copy_if_missing(DEFAULT_TRIGGERS, paths.message_triggers)
        if configured_database is None:
            return str(paths.tokens), database_url
        relocated_url = make_url(database_url).set(database=str(paths.database))
        return str(paths.tokens), relocated_url.render_as_string(hide_password=False)
    except (OSError, sqlite3.Error) as error:
        raise RuntimeDataError("Could not prepare the application data directory") from error
