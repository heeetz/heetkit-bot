"""One platform-owned home for mutable application data."""

from __future__ import annotations

import os
import shutil
import tempfile
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
DEFAULT_TRIGGERS = _PACKAGE_ROOT / "resources" / "default_triggers.json"
DEFAULT_FILTERS = _PACKAGE_ROOT / "resources" / "filters"
PACKAGED_FRONTEND = _PACKAGE_ROOT / "resources" / "frontend" / "index.html"
DATA_DIR_ENV = "HEETKIT_DATA_DIR"
FILTER_NAMES = ("blocked_words.txt", "blocked_phrases.txt", "blocked_patterns.txt")


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    root: Path

    @classmethod
    def default(cls) -> RuntimePaths:
        if override := os.environ.get(DATA_DIR_ENV):
            return cls(Path(override).expanduser().resolve())
        return cls(user_data_path("HeetKit", appauthor=False))

    @property
    def is_default_profile(self) -> bool:
        return self.root.resolve() == user_data_path("HeetKit", appauthor=False).resolve()

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
        return self.data / "heetkit.db"

    @property
    def tokens(self) -> Path:
        return self.auth / "twitchio_tokens.json"


class RuntimeDataError(RuntimeError):
    """The application data directory could not be prepared."""


def _copy_if_missing(source: Path, destination: Path) -> None:
    if destination.exists() or not source.is_file():
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
        if not destination.exists():
            temporary.replace(destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def prepare_runtime_data(
    database_url: str,
    *,
    paths: RuntimePaths | None = None,
) -> tuple[str, str]:
    """Seed missing profile defaults and return the canonical runtime locations."""
    paths = paths or RuntimePaths.default()
    try:
        for directory in (paths.config, paths.data, paths.auth, paths.cache, paths.filters):
            directory.mkdir(parents=True, exist_ok=True)
        for filename in FILTER_NAMES:
            _copy_if_missing(DEFAULT_FILTERS / filename, paths.filters / filename)
        _copy_if_missing(DEFAULT_TRIGGERS, paths.message_triggers)
    except OSError as error:
        raise RuntimeDataError("Could not prepare the application data directory") from error

    url = make_url(database_url)
    if url.drivername.startswith("sqlite") and url.database and url.database != ":memory:":
        database_url = url.set(database=str(paths.database)).render_as_string(hide_password=False)
    return str(paths.tokens), database_url
