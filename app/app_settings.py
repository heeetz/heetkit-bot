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

from app.config.ai_models import validate_ai_provider, validate_provider_models
from app.settings_recovery import preserve_settings_recovery
from app.config.ai import AI_MEMORY_ENABLED
from app.config.privacy import AI_HISTORY_MAX_ENTRIES, AI_CONTEXT_MAX_ENTRIES, validate_memory_limits
from app.config.ai_setup import AIModelSelection, AISetup, parse_ai_setup
from app.config.ai_language import ResponseLanguageSettings, validate_response_language

logger = logging.getLogger(__name__)
APP_SETTINGS_VERSION = 1
OPERATION_MODES = frozenset({"always_on", "stream_only", "manual", "disabled"})


@dataclass(frozen=True, slots=True)
class WindowSettings:
    start_minimized: bool = False
    minimize_to_tray: bool = False
    close_to_tray: bool = False


@dataclass(frozen=True, slots=True)
class StartupSettings:
    auto_start_bot: bool = False
    # Headless only. Desktop continues to use auto_start_bot.
    operation_mode: str = "always_on"


@dataclass(frozen=True, slots=True)
class AISettings:
    memory_enabled: bool = AI_MEMORY_ENABLED
    history_max_entries: int = AI_HISTORY_MAX_ENTRIES
    context_max_entries: int = AI_CONTEXT_MAX_ENTRIES
    selected_model: str | None = None
    fallback_model: str | None = None
    # None preserves intentional process defaults; old profiles still default to Gemini.
    provider: str | None = None
    deepseek_selected_model: str | None = None
    deepseek_fallback_model: str | None = None
    openai_selected_model: str | None = None
    openai_fallback_model: str | None = None
    # Optional per-account policy; internal AI/output bounds remain code-owned.
    cooldown_bypass_user_id: str | None = None
    response_language: ResponseLanguageSettings = field(default_factory=ResponseLanguageSettings)
    setup: AISetup | None = None
    setup_guide_dismissed: bool = False
    setup_guide_ai_skipped: bool = False


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
    unsafe_defaults = replace(defaults, startup=StartupSettings(operation_mode="disabled"))
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
        return unsafe_defaults
    if not isinstance(payload, dict):
        logger.warning("Application settings file must contain a JSON object; using defaults")
        return unsafe_defaults

    if "version" not in payload:
        window_payload = payload
        startup_payload: dict[str, object] = {}
        ai_payload: dict[str, object] = {}
    elif type(payload["version"]) is not int or payload["version"] != APP_SETTINGS_VERSION:
        logger.warning(
            "Unsupported application settings version=%r; using defaults",
            payload["version"],
        )
        return unsafe_defaults
    else:
        window_payload = _read_section(payload, "window")
        startup_payload = _read_section(payload, "startup")
        ai_payload = _read_section(payload, "ai")
    operation_mode = startup_payload.get("operation_mode", "always_on")
    if (("startup" in payload and not isinstance(payload["startup"], dict))
            or not isinstance(operation_mode, str) or operation_mode not in OPERATION_MODES):
        logger.warning("Invalid headless operation mode; keeping Twitch disabled")
        operation_mode = "disabled"
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
    cooldown_bypass_user_id = _read_optional_string(ai_payload, "ai", "cooldown_bypass_user_id")
    if cooldown_bypass_user_id is not None and re.fullmatch(r"[0-9]+", cooldown_bypass_user_id) is None:
        logger.warning("Ignoring invalid application setting name=ai.cooldown_bypass_user_id")
        cooldown_bypass_user_id = None
    if selected_model is not None and fallback_model is not None:
        try:
            selected_model, fallback_model = validate_provider_models(
                "gemini",
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

    response_language = ResponseLanguageSettings()
    try:
        provider = validate_ai_provider(ai_payload["provider"]) if ai_payload.get("provider") is not None else None
    except ValueError:
        logger.warning("Ignoring invalid AI provider selection")
        provider = None
    deepseek_selected = ai_payload.get("deepseek_selected_model")
    deepseek_fallback = ai_payload.get("deepseek_fallback_model")
    if deepseek_selected is not None or deepseek_fallback is not None:
        try:
            deepseek_selected, deepseek_fallback = validate_provider_models("deepseek", deepseek_selected, deepseek_fallback)
        except ValueError:
            logger.warning("Ignoring invalid DeepSeek model settings override")
            deepseek_selected = deepseek_fallback = None
    openai_selected = ai_payload.get("openai_selected_model")
    openai_fallback = ai_payload.get("openai_fallback_model")
    if openai_selected is not None or openai_fallback is not None:
        try:
            openai_selected, openai_fallback = validate_provider_models("openai", openai_selected, openai_fallback)
        except ValueError:
            logger.warning("Ignoring invalid OpenAI model settings override")
            openai_selected = openai_fallback = None
    if "response_language" in ai_payload:
        language_payload = ai_payload["response_language"]
        try:
            if not isinstance(language_payload, dict):
                raise ValueError("Response language settings must be an object.")
            response_language = validate_response_language(
                language_payload.get("mode"),
                language_payload.get("allowed_languages"),
                language_payload.get("fallback_language"),
            )
        except ValueError:
            logger.warning("Ignoring invalid application setting name=ai.response_language")

    setup = None
    if ai_payload.get("setup") is not None:
        try:
            setup = parse_ai_setup(ai_payload["setup"], capabilities=False, require_consent=False)
        except ValueError:
            logger.warning("Invalid saved AI setup; retaining legacy model settings")
    try:
        history_limit, context_limit = validate_memory_limits(ai_payload.get("history_max_entries", AI_HISTORY_MAX_ENTRIES),
                                                             ai_payload.get("context_max_entries", AI_CONTEXT_MAX_ENTRIES))
    except ValueError:
        # Reject invalid policy rather than silently expanding a requested cap.
        raise ValueError("Invalid saved AI history/context limits; correct profile settings before startup.") from None
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
            operation_mode=operation_mode,
            auto_start_bot=_read_boolean(
                startup_payload,
                "startup",
                "auto_start_bot",
                defaults.startup.auto_start_bot,
            ),
        ),
        ai=AISettings(
            history_max_entries=history_limit,
            context_max_entries=context_limit,
            memory_enabled=_read_boolean(
                ai_payload,
                "ai",
                "memory_enabled",
                defaults.ai.memory_enabled,
            ),
            selected_model=selected_model,
            fallback_model=fallback_model,
            provider=provider,
            deepseek_selected_model=deepseek_selected,
            deepseek_fallback_model=deepseek_fallback,
            openai_selected_model=openai_selected,
            openai_fallback_model=openai_fallback,
            cooldown_bypass_user_id=cooldown_bypass_user_id,
            response_language=response_language,
            setup=setup,
            setup_guide_dismissed=_read_boolean(ai_payload, "ai", "setup_guide_dismissed", False),
            setup_guide_ai_skipped=_read_boolean(ai_payload, "ai", "setup_guide_ai_skipped", False),
        ),
        twitch=twitch,
    )


def save_app_settings(
    path: Path, settings: AppSettings, *, recovered_settings: AppSettings | None = None,
) -> None:
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
        preserve_settings_recovery(
            path,
            None if recovered_settings is None else {"version": APP_SETTINGS_VERSION, **asdict(recovered_settings)},
            version=APP_SETTINGS_VERSION,
            allow_legacy=True,
        )
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

    def update_operation_mode(self, mode: object) -> AppSettings:
        if not isinstance(mode, str) or mode not in OPERATION_MODES:
            raise ValueError("Unknown operation mode.")
        with self._lock:
            updated = replace(self._settings, startup=replace(self._settings.startup, operation_mode=mode))
            save_app_settings(self._path, updated, recovered_settings=self._settings)
            self._settings = updated
        return updated

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
            save_app_settings(self._path, updated, recovered_settings=self._settings)
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
                startup=replace(self._settings.startup, auto_start_bot=auto_start_bot),
                ai=self._settings.ai,
                twitch=self._settings.twitch,
            )
            save_app_settings(self._path, updated, recovered_settings=self._settings)
            self._settings = updated
        return updated

    def update_ai_memory_limits(self, *, stored: object, context: object) -> AppSettings:
        stored, context = validate_memory_limits(stored, context)
        with self._lock:
            updated = replace(self._settings, ai=replace(self._settings.ai,
                              history_max_entries=stored, context_max_entries=context))
            save_app_settings(self._path, updated, recovered_settings=self._settings)
            self._settings = updated
        return updated

    def update_ai_memory(self, *, enabled: object) -> AppSettings:
        if type(enabled) is not bool:
            raise ValueError("AI memory setting must be a boolean value.")
        with self._lock:
            updated = AppSettings(
                window=self._settings.window,
                startup=self._settings.startup,
                ai=replace(self._settings.ai, memory_enabled=enabled),
                twitch=self._settings.twitch,
            )
            save_app_settings(self._path, updated, recovered_settings=self._settings)
            self._settings = updated
        return updated

    def update_ai_models(
        self,
        *,
        selected_model: object = None,
        fallback_model: object = None,
        provider: object = "gemini",
    ) -> AppSettings:
        provider = validate_ai_provider(provider)
        changes = {"provider": provider}
        if selected_model is not None or fallback_model is not None:
            selected, fallback = validate_provider_models(provider, selected_model, fallback_model)
            prefix = provider + "_" if provider != "gemini" else ""
            changes.update({prefix + "selected_model": selected, prefix + "fallback_model": fallback})
        with self._lock:
            if self._settings.ai.setup is not None:
                existing = self._settings.ai.setup
                if selected_model is None and fallback_model is None:
                    raise ValueError("Choose both models when changing a configured AI setup through the legacy model operation.")
                def compatible(previous, model):
                    if previous and previous.provider == provider and previous.model == model:
                        return previous
                    return AIModelSelection(provider, model, "off" if provider == "deepseek" else "default")
                configured = replace(existing, primary=compatible(existing.primary, selected),
                                     fallback=compatible(existing.fallback, fallback), cross_provider_acknowledged=False)
                changes["setup"] = parse_ai_setup(asdict(configured))
            updated = AppSettings(
                window=self._settings.window,
                startup=self._settings.startup,
                ai=replace(self._settings.ai, **changes),
                twitch=self._settings.twitch,
            )
            save_app_settings(self._path, updated, recovered_settings=self._settings)
            self._settings = updated
        return updated

    def update_ai_setup(self, payload: object) -> AppSettings:
        setup = parse_ai_setup(payload)
        with self._lock:
            updated = replace(self._settings, ai=replace(self._settings.ai, setup=setup,
                                                       provider=setup.primary.provider))
            save_app_settings(self._path, updated, recovered_settings=self._settings)
            self._settings = updated
        return updated

    def update_setup_guide(self, dismissed: object, ai_skipped: object) -> AppSettings:
        if type(dismissed) is not bool or type(ai_skipped) is not bool:
            raise ValueError("Setup guide preferences must be boolean.")
        with self._lock:
            updated = replace(self._settings, ai=replace(self._settings.ai,
                              setup_guide_dismissed=dismissed, setup_guide_ai_skipped=ai_skipped))
            save_app_settings(self._path, updated, recovered_settings=self._settings)
            self._settings = updated
        return updated

    def update_ai_response_language(
        self, *, mode: object, allowed_languages: object, fallback_language: object,
    ) -> AppSettings:
        language = validate_response_language(mode, allowed_languages, fallback_language)
        with self._lock:
            updated = replace(
                self._settings, ai=replace(self._settings.ai, response_language=language),
            )
            save_app_settings(self._path, updated, recovered_settings=self._settings)
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
            save_app_settings(self._path, updated, recovered_settings=self._settings)
            self._settings = updated
        return updated

    def save_twitch_preset(
        self,
        *,
        display_name: object,
        channel: object,
        channel_user_id: object,
        preset_id: object = None,
        update_target: bool = True,
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
                    channel=parsed_channel if update_target else self._settings.twitch.channel,
                    channel_user_id=parsed_channel_user_id if update_target else self._settings.twitch.channel_user_id,
                    presets=presets,
                    selected_preset_id=parsed_id if update_target else None,
                ),
            )
            save_app_settings(self._path, updated, recovered_settings=self._settings)
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
            save_app_settings(self._path, updated, recovered_settings=self._settings)
            self._settings = updated
        return updated
