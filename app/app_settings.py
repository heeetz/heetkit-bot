"""Persistent local desktop application settings."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import RLock

from config import AI_MEMORY_ENABLED

logger = logging.getLogger(__name__)
APP_SETTINGS_VERSION = 1


@dataclass(frozen=True, slots=True)
class WindowSettings:
    start_minimized: bool = False
    minimize_to_tray: bool = False
    close_to_tray: bool = False


@dataclass(frozen=True, slots=True)
class AISettings:
    memory_enabled: bool = AI_MEMORY_ENABLED


@dataclass(frozen=True, slots=True)
class AppSettings:
    window: WindowSettings = field(default_factory=WindowSettings)
    ai: AISettings = field(default_factory=AISettings)


def _read_boolean(
    section: dict[str, object],
    section_name: str,
    field_name: str,
    default: bool,
) -> bool:
    if field_name not in section:
        return default
    value = section[field_name]
    if type(value) is bool:
        return value
    logger.warning(
        "Ignoring invalid application setting name=%s.%s",
        section_name,
        field_name,
    )
    return default


def _read_section(payload: dict[str, object], section_name: str) -> dict[str, object]:
    section = payload.get(section_name, {})
    if isinstance(section, dict):
        return section
    logger.warning("Ignoring malformed application settings section name=%s", section_name)
    return {}


def load_app_settings(path: Path) -> AppSettings:
    defaults = AppSettings()
    if not path.exists():
        return defaults
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        logger.warning(
            "Could not load desktop settings path=%s error=%s; using defaults",
            path,
            type(error).__name__,
        )
        return defaults
    if not isinstance(payload, dict):
        logger.warning("Application settings file must contain a JSON object; using defaults")
        return defaults

    if "version" not in payload:
        window_payload = payload
        ai_payload: dict[str, object] = {}
    elif type(payload["version"]) is not int or payload["version"] != APP_SETTINGS_VERSION:
        logger.warning(
            "Unsupported application settings version=%r; using defaults",
            payload["version"],
        )
        return defaults
    else:
        window_payload = _read_section(payload, "window")
        ai_payload = _read_section(payload, "ai")

    return AppSettings(
        window=WindowSettings(
            start_minimized=_read_boolean(
                window_payload,
                "window",
                "start_minimized",
                defaults.window.start_minimized,
            ),
            minimize_to_tray=_read_boolean(
                window_payload,
                "window",
                "minimize_to_tray",
                defaults.window.minimize_to_tray,
            ),
            close_to_tray=_read_boolean(
                window_payload,
                "window",
                "close_to_tray",
                defaults.window.close_to_tray,
            ),
        ),
        ai=AISettings(
            memory_enabled=_read_boolean(
                ai_payload,
                "ai",
                "memory_enabled",
                defaults.ai.memory_enabled,
            )
        ),
    )


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
            payload = {"version": APP_SETTINGS_VERSION, **asdict(settings)}
            json.dump(payload, temporary_file, indent=2, sort_keys=True)
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

    def update_window(
        self,
        *,
        start_minimized: object,
        minimize_to_tray: object,
        close_to_tray: object,
    ) -> AppSettings:
        values = (start_minimized, minimize_to_tray, close_to_tray)
        if any(type(value) is not bool for value in values):
            raise ValueError("Application window settings must be boolean values.")
        window = WindowSettings(
            start_minimized=start_minimized,
            minimize_to_tray=minimize_to_tray,
            close_to_tray=close_to_tray,
        )
        with self._lock:
            updated = AppSettings(window=window, ai=self._settings.ai)
            save_app_settings(self._path, updated)
            self._settings = updated
        return updated

    def update_ai_memory(self, *, enabled: object) -> AppSettings:
        if type(enabled) is not bool:
            raise ValueError("AI memory setting must be a boolean value.")
        with self._lock:
            updated = AppSettings(
                window=self._settings.window,
                ai=AISettings(memory_enabled=enabled),
            )
            save_app_settings(self._path, updated)
            self._settings = updated
        return updated
