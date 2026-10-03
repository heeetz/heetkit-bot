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


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LEGACY_DATA = PROJECT_ROOT / "data"
FILTER_NAMES = ("blocked_words.txt", "blocked_phrases.txt", "blocked_patterns.txt")


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    root: Path

    @classmethod
    def default(cls) -> RuntimePaths:
        return cls(user_data_path("TwitchBot", appauthor=False))

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


def _sqlite_file(database_url: str) -> Path | None:
    url = make_url(database_url)
    if not url.drivername.startswith("sqlite") or not url.database or url.database == ":memory:":
        return None
    return Path(url.database).resolve()


def prepare_runtime_data(
    token_file: str,
    database_url: str,
    *,
    paths: RuntimePaths | None = None,
    legacy_data: Path = LEGACY_DATA,
) -> tuple[str, str]:
    """Copy legacy state once, then return canonical token and SQLite locations.

    Old files remain in place. A marker prevents deleted settings from being
    restored from the old checkout on a later launch. SQLite uses its backup API
    so WAL contents are included in the migration.
    """
    paths = paths or RuntimePaths.default()
    try:
        for directory in (paths.config, paths.data, paths.auth, paths.cache, paths.filters):
            directory.mkdir(parents=True, exist_ok=True)
        for filename in FILTER_NAMES:
            _copy_if_missing(legacy_data / "filters" / filename, paths.filters / filename)
        configured_database = _sqlite_file(database_url)
        if not paths.migration_marker.exists():
            for filename, destination in (
                ("app_settings.json", paths.app_settings),
                ("command_settings.json", paths.command_settings),
                ("personality_settings.json", paths.personality_settings),
            ):
                _copy_if_missing(legacy_data / filename, destination)

            configured_token = Path(token_file).resolve()
            token_source = (
                configured_token if configured_token.is_file() else legacy_data / "twitchio_tokens.json"
            )
            _copy_if_missing(token_source, paths.tokens, secret=True)

            if configured_database is not None:
                database_source = (
                    configured_database if configured_database.is_file() else legacy_data / "twitch_bot.db"
                )
                _backup_sqlite_if_missing(database_source, paths.database)
            paths.migration_marker.touch()
        if configured_database is None:
            return str(paths.tokens), database_url
        relocated_url = make_url(database_url).set(database=str(paths.database))
        return str(paths.tokens), relocated_url.render_as_string(hide_password=False)
    except (OSError, sqlite3.Error) as error:
        raise RuntimeDataError("Could not prepare the application data directory") from error
