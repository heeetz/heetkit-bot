"""Persistent local desktop application settings."""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import uuid
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from threading import RLock

from app.config.ai_models import validate_gemini_model_settings
from config import AI_MEMORY_ENABLED

logger = logging.getLogger(__name__)
APP_SETTINGS_VERSION = 1


@dataclass(frozen=True, slots=True)
class WindowSettings:
    start_minimized: bool = False
    minimize_to_tray: bool = False
    close_to_tray: bool = False


@dataclass(frozen=True, slots=True)
class StartupSettings:
    auto_start_bot: bool = False


@dataclass(frozen=True, slots=True)
class AISettings:
    memory_enabled: bool = AI_MEMORY_ENABLED
    selected_model: str | None = None
    fallback_model: str | None = None


@dataclass(frozen=True, slots=True)
class TwitchConnectionPreset:
    id: str
    display_name: str
    channel: str
    channel_user_id: str


@dataclass(frozen=True, slots=True)
class TwitchSettings:
    channel: str | None = None
    channel_user_id: str | None = None
    presets: tuple[TwitchConnectionPreset, ...] = ()
    selected_preset_id: str | None = None
    client_id: str | None = None
    bot_username: str | None = None
    bot_user_id: str | None = None


@dataclass(frozen=True, slots=True)
class AppSettings:
    window: WindowSettings = field(default_factory=WindowSettings)
    startup: StartupSettings = field(default_factory=StartupSettings)
    ai: AISettings = field(default_factory=AISettings)
    twitch: TwitchSettings = field(default_factory=TwitchSettings)


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


def _read_optional_string(
    section: dict[str, object],
    section_name: str,
    field_name: str,
) -> str | None:
    value = section.get(field_name)
    if value is None:
        return None
    if isinstance(value, str) and value.strip():
        return value.strip()
    logger.warning(
        "Ignoring invalid application setting name=%s.%s",
        section_name,
        field_name,
    )
    return None


def _validate_twitch_target(channel: object, channel_user_id: object) -> tuple[str, str]:
    if not isinstance(channel, str) or not channel.strip():
        raise ValueError("Twitch target channel must not be empty.")
    parsed_channel = channel.strip().lower().removeprefix("#")
    if not parsed_channel or any(character.isspace() for character in parsed_channel):
        raise ValueError("Twitch target channel must not contain whitespace.")
    if len(parsed_channel) > 100:
        raise ValueError("Twitch target channel is too long.")
    if not isinstance(channel_user_id, str) or not channel_user_id.strip().isdigit():
        raise ValueError("Twitch channel user ID must contain digits only.")
    return parsed_channel, channel_user_id.strip()


def _validate_preset_id(preset_id: object) -> str:
    if not isinstance(preset_id, str) or not re.fullmatch(
        r"[A-Za-z0-9_-]{1,64}", preset_id
    ):
        raise ValueError("Twitch preset ID is invalid.")
    return preset_id


def validate_twitch_identity(
    client_id: object, bot_username: object, bot_user_id: object,
) -> tuple[str, str, str]:
    if not isinstance(client_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", client_id.strip()):
        raise ValueError("Twitch client ID must contain only letters, digits, underscores or hyphens.")
    if not isinstance(bot_username, str) or not re.fullmatch(r"[A-Za-z0-9_]{1,25}", bot_username.strip()):
        raise ValueError("Twitch bot username must be a login name with letters, digits or underscores.")
    if not isinstance(bot_user_id, str) or not re.fullmatch(r"[0-9]{1,20}", bot_user_id.strip()):
        raise ValueError("Twitch bot user ID must contain digits only.")
    return client_id.strip(), bot_username.strip().lower(), bot_user_id.strip()


def _validate_preset_name(display_name: object) -> str:
    if not isinstance(display_name, str) or not display_name.strip():
        raise ValueError("Twitch preset name must not be empty.")
    parsed_name = display_name.strip()
    if len(parsed_name) > 80:
        raise ValueError("Twitch preset name is too long.")
    return parsed_name


def validate_twitch_settings(
    channel: object,
    channel_user_id: object,
    *,
    presets: tuple[TwitchConnectionPreset, ...] = (),
    selected_preset_id: object = None,
) -> TwitchSettings:
    parsed_channel, parsed_channel_user_id = _validate_twitch_target(
        channel,
        channel_user_id,
    )
    parsed_selected_preset_id: str | None = None
    if selected_preset_id is not None:
        parsed_selected_preset_id = _validate_preset_id(selected_preset_id)
        selected = next(
            (preset for preset in presets if preset.id == parsed_selected_preset_id),
            None,
        )
        if selected is None:
            raise ValueError("Unknown Twitch connection preset.")
        if (
            selected.channel != parsed_channel
            or selected.channel_user_id != parsed_channel_user_id
        ):
            raise ValueError("Selected Twitch preset does not match the target channel.")
    return TwitchSettings(
        channel=parsed_channel,
        channel_user_id=parsed_channel_user_id,
        presets=presets,
        selected_preset_id=parsed_selected_preset_id,
    )


def _read_twitch_presets(section: dict[str, object]) -> tuple[TwitchConnectionPreset, ...]:
    payload = section.get("presets", [])
    if not isinstance(payload, list):
        logger.warning("Ignoring malformed application setting name=twitch.presets")
        return ()

    presets: list[TwitchConnectionPreset] = []
    known_ids: set[str] = set()
    known_names: set[str] = set()
    for item in payload:
        if not isinstance(item, dict):
            logger.warning("Ignoring malformed Twitch connection preset")
            continue
        try:
            preset_id = _validate_preset_id(item.get("id"))
            display_name = _validate_preset_name(item.get("display_name"))
            channel, channel_user_id = _validate_twitch_target(
                item.get("channel"),
                item.get("channel_user_id"),
            )
        except ValueError:
            logger.warning("Ignoring invalid Twitch connection preset")
            continue
        normalized_name = display_name.casefold()
        if preset_id in known_ids or normalized_name in known_names:
            logger.warning("Ignoring duplicate Twitch connection preset")
            continue
        known_ids.add(preset_id)
        known_names.add(normalized_name)
        presets.append(
            TwitchConnectionPreset(
                id=preset_id,
                display_name=display_name,
                channel=channel,
                channel_user_id=channel_user_id,
            )
        )
    return tuple(presets)


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
        startup_payload: dict[str, object] = {}
        ai_payload: dict[str, object] = {}
    elif type(payload["version"]) is not int or payload["version"] != APP_SETTINGS_VERSION:
        logger.warning(
            "Unsupported application settings version=%r; using defaults",
            payload["version"],
        )
        return defaults
    else:
        window_payload = _read_section(payload, "window")
        startup_payload = _read_section(payload, "startup")
        ai_payload = _read_section(payload, "ai")
    twitch_payload = (
        {} if "version" not in payload else _read_section(payload, "twitch")
    )
    twitch_channel = _read_optional_string(twitch_payload, "twitch", "channel")
    twitch_channel_user_id = _read_optional_string(
        twitch_payload,
        "twitch",
        "channel_user_id",
    )
    twitch_presets = _read_twitch_presets(twitch_payload)
    selected_preset_id = _read_optional_string(
        twitch_payload,
        "twitch",
        "selected_preset_id",
    )
    if twitch_channel is not None and twitch_channel_user_id is not None:
        try:
            twitch = validate_twitch_settings(
                twitch_channel,
                twitch_channel_user_id,
                presets=twitch_presets,
                selected_preset_id=selected_preset_id,
            )
        except ValueError:
            logger.warning("Ignoring invalid Twitch preset selection")
            try:
                twitch = validate_twitch_settings(
                    twitch_channel,
                    twitch_channel_user_id,
                    presets=twitch_presets,
                )
            except ValueError:
                logger.warning("Ignoring invalid Twitch application settings override")
                twitch = TwitchSettings(presets=twitch_presets)
    else:
        if (twitch_channel is None) != (twitch_channel_user_id is None):
            logger.warning("Ignoring incomplete Twitch application settings override")
        if selected_preset_id is not None:
            logger.warning("Ignoring Twitch preset selection without a target channel")
        twitch = TwitchSettings(presets=twitch_presets)

    identity = tuple(_read_optional_string(twitch_payload, "twitch", name)
                     for name in ("client_id", "bot_username", "bot_user_id"))
    if any(value is not None for value in identity):
        try:
            client_id, bot_username, bot_user_id = validate_twitch_identity(*identity)
            twitch = replace(twitch, client_id=client_id, bot_username=bot_username, bot_user_id=bot_user_id)
        except ValueError:
            logger.warning("Ignoring invalid or incomplete Twitch identity override")

    selected_model = _read_optional_string(ai_payload, "ai", "selected_model")
    fallback_model = _read_optional_string(ai_payload, "ai", "fallback_model")
    if selected_model is not None and fallback_model is not None:
        try:
            selected_model, fallback_model = validate_gemini_model_settings(
                selected_model,
                fallback_model,
            )
        except ValueError:
            logger.warning("Ignoring invalid Gemini model settings override")
            selected_model = None
            fallback_model = None
    elif (selected_model is None) != (fallback_model is None):
        logger.warning("Ignoring incomplete Gemini model settings override")
        selected_model = None
        fallback_model = None

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
        startup=StartupSettings(
            auto_start_bot=_read_boolean(
                startup_payload,
                "startup",
                "auto_start_bot",
                defaults.startup.auto_start_bot,
            ),
        ),
        ai=AISettings(
            memory_enabled=_read_boolean(
                ai_payload,
                "ai",
                "memory_enabled",
                defaults.ai.memory_enabled,
            ),
            selected_model=selected_model,
            fallback_model=fallback_model,
        ),
        twitch=twitch,
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
            updated = AppSettings(
                window=window,
                startup=self._settings.startup,
                ai=self._settings.ai,
                twitch=self._settings.twitch,
            )
            save_app_settings(self._path, updated)
            self._settings = updated
        return updated

    def update_desktop(
        self,
        *,
        start_minimized: object,
        minimize_to_tray: object,
        close_to_tray: object,
        auto_start_bot: object,
    ) -> AppSettings:
        values = (
            start_minimized,
            minimize_to_tray,
            close_to_tray,
            auto_start_bot,
        )
        if any(type(value) is not bool for value in values):
            raise ValueError("Desktop settings must be boolean values.")
        with self._lock:
            updated = AppSettings(
                window=WindowSettings(
                    start_minimized=start_minimized,
                    minimize_to_tray=minimize_to_tray,
                    close_to_tray=close_to_tray,
                ),
                startup=StartupSettings(auto_start_bot=auto_start_bot),
                ai=self._settings.ai,
                twitch=self._settings.twitch,
            )
            save_app_settings(self._path, updated)
            self._settings = updated
        return updated

    def update_ai_memory(self, *, enabled: object) -> AppSettings:
        if type(enabled) is not bool:
            raise ValueError("AI memory setting must be a boolean value.")
        with self._lock:
            updated = AppSettings(
                window=self._settings.window,
                startup=self._settings.startup,
                ai=AISettings(
                    memory_enabled=enabled,
                    selected_model=self._settings.ai.selected_model,
                    fallback_model=self._settings.ai.fallback_model,
                ),
                twitch=self._settings.twitch,
            )
            save_app_settings(self._path, updated)
            self._settings = updated
        return updated

    def update_ai_models(
        self,
        *,
        selected_model: object,
        fallback_model: object,
    ) -> AppSettings:
        selected, fallback = validate_gemini_model_settings(
            selected_model,
            fallback_model,
        )
        with self._lock:
            updated = AppSettings(
                window=self._settings.window,
                startup=self._settings.startup,
                ai=AISettings(
                    memory_enabled=self._settings.ai.memory_enabled,
                    selected_model=selected,
                    fallback_model=fallback,
                ),
                twitch=self._settings.twitch,
            )
            save_app_settings(self._path, updated)
            self._settings = updated
        return updated

    def update_twitch(
        self,
        *,
        channel: object,
        channel_user_id: object,
        selected_preset_id: object = None,
        client_id: object = None,
        bot_username: object = None,
        bot_user_id: object = None,
    ) -> AppSettings:
        with self._lock:
            twitch = validate_twitch_settings(
                channel,
                channel_user_id,
                presets=self._settings.twitch.presets,
                selected_preset_id=selected_preset_id,
            )
            identity = (client_id, bot_username, bot_user_id)
            if any(value is not None for value in identity):
                client_id, bot_username, bot_user_id = validate_twitch_identity(*identity)
            else:
                current = self._settings.twitch
                client_id, bot_username, bot_user_id = current.client_id, current.bot_username, current.bot_user_id
            twitch = replace(twitch, client_id=client_id, bot_username=bot_username, bot_user_id=bot_user_id)
            updated = AppSettings(
                window=self._settings.window,
                startup=self._settings.startup,
                ai=self._settings.ai,
                twitch=twitch,
            )
            save_app_settings(self._path, updated)
            self._settings = updated
        return updated

    def save_twitch_preset(
        self,
        *,
        display_name: object,
        channel: object,
        channel_user_id: object,
        preset_id: object = None,
    ) -> tuple[AppSettings, TwitchConnectionPreset]:
        parsed_name = _validate_preset_name(display_name)
        parsed_channel, parsed_channel_user_id = _validate_twitch_target(
            channel,
            channel_user_id,
        )
        with self._lock:
            existing = self._settings.twitch.presets
            if preset_id is None:
                parsed_id = uuid.uuid4().hex
            else:
                parsed_id = _validate_preset_id(preset_id)
                if not any(preset.id == parsed_id for preset in existing):
                    raise ValueError("Unknown Twitch connection preset.")
            if any(
                preset.id != parsed_id
                and preset.display_name.casefold() == parsed_name.casefold()
                for preset in existing
            ):
                raise ValueError("A Twitch preset with this name already exists.")
            preset = TwitchConnectionPreset(
                id=parsed_id,
                display_name=parsed_name,
                channel=parsed_channel,
                channel_user_id=parsed_channel_user_id,
            )
            presets = tuple(
                preset if item.id == parsed_id else item for item in existing
            )
            if not any(item.id == parsed_id for item in existing):
                presets = (*presets, preset)
            updated = AppSettings(
                window=self._settings.window,
                startup=self._settings.startup,
                ai=self._settings.ai,
                twitch=replace(
                    self._settings.twitch,
                    channel=parsed_channel,
                    channel_user_id=parsed_channel_user_id,
                    presets=presets,
                    selected_preset_id=parsed_id,
                ),
            )
            save_app_settings(self._path, updated)
            self._settings = updated
        return updated, preset

    def delete_twitch_preset(self, preset_id: object) -> AppSettings:
        parsed_id = _validate_preset_id(preset_id)
        with self._lock:
            current = self._settings.twitch
            if not any(preset.id == parsed_id for preset in current.presets):
                raise ValueError("Unknown Twitch connection preset.")
            updated = AppSettings(
                window=self._settings.window,
                startup=self._settings.startup,
                ai=self._settings.ai,
                twitch=replace(
                    current,
                    channel=current.channel,
                    channel_user_id=current.channel_user_id,
                    presets=tuple(
                        preset for preset in current.presets if preset.id != parsed_id
                    ),
                    selected_preset_id=(
                        None
                        if current.selected_preset_id == parsed_id
                        else current.selected_preset_id
                    ),
                ),
            )
            save_app_settings(self._path, updated)
            self._settings = updated
        return updated
