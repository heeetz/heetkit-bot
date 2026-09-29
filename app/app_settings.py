"""Persistent local desktop application settings."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import RLock

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AppSettings:
    start_minimized: bool = False
    minimize_to_tray: bool = False
    close_to_tray: bool = False


def load_app_settings(path: Path) -> AppSettings:
    if not path.exists():
        return AppSettings()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        logger.warning(
            "Could not load desktop settings path=%s error=%s; using defaults",
            path,
            type(error).__name__,
        )
        return AppSettings()
    if not isinstance(payload, dict):
        logger.warning("Desktop settings file must contain a JSON object; using defaults")
        return AppSettings()

    values: dict[str, bool] = {}
    for field_name in ("start_minimized", "minimize_to_tray", "close_to_tray"):
        value = payload.get(field_name, False)
        if type(value) is bool:
            values[field_name] = value
        else:
            logger.warning("Ignoring invalid desktop setting name=%s", field_name)
            values[field_name] = False
    return AppSettings(**values)


def save_app_settings(path: Path, settings: AppSettings) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            json.dump(asdict(settings), temporary_file, indent=2, sort_keys=True)
            temporary_file.write("\n")
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


class AppSettingsStore:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._lock = RLock()
        self._settings = load_app_settings(self._path)

    def snapshot(self) -> AppSettings:
        with self._lock:
            return self._settings

    def update(
        self,
        *,
        start_minimized: object,
        minimize_to_tray: object,
        close_to_tray: object,
    ) -> AppSettings:
        values = (start_minimized, minimize_to_tray, close_to_tray)
        if any(type(value) is not bool for value in values):
            raise ValueError("Desktop settings must be boolean values.")
        updated = AppSettings(
            start_minimized=start_minimized,
            minimize_to_tray=minimize_to_tray,
            close_to_tray=close_to_tray,
        )
        with self._lock:
            save_app_settings(self._path, updated)
            self._settings = updated
        return updated
