"""Persistent local desktop application settings."""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import asdict, dataclass, field, replace
from threading import RLock

from app.errors import UserError
from typing import Annotated, Literal
from pydantic import BeforeValidator, Field, StrictBool, StrictInt, StrictStr, StringConstraints, model_validator
from app.settings_models import (SettingsModel, InterfaceLanguage, OperationMode,
    field_value, parse)
from app.config.ai_models import validate_ai_provider, validate_provider_models
from app.config_file import ConfigFile, ConfigSection
from app.config.ai import AI_MEMORY_ENABLED
from app.config.privacy import AI_HISTORY_MAX_ENTRIES, AI_CONTEXT_MAX_ENTRIES
from app.config.ai_setup import AISetup, parse_ai_setup
from app.config.ai_language import ResponseLanguageSettings, validate_response_language

logger = logging.getLogger(__name__)
APP_SETTINGS_VERSION = 1
OPERATION_MODES = frozenset({"always_on", "stream_only", "manual", "disabled"})
# Desktop UI languages (task 2.2). Server keeps its choice in the browser instead.
INTERFACE_LANGUAGES = ("en", "uk", "ru")
DEFAULT_INTERFACE_LANGUAGE = "en"


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
class InterfaceSettings:
    language: str = DEFAULT_INTERFACE_LANGUAGE


@dataclass(frozen=True, slots=True)
class AppSettings:
    window: WindowSettings = field(default_factory=WindowSettings)
    startup: StartupSettings = field(default_factory=StartupSettings)
    ai: AISettings = field(default_factory=AISettings)
    twitch: TwitchSettings = field(default_factory=TwitchSettings)
    interface: InterfaceSettings = field(default_factory=InterfaceSettings)


class WindowSettingsModel(SettingsModel):
    start_minimized: StrictBool = False
    minimize_to_tray: StrictBool = False
    close_to_tray: StrictBool = False


class StartupSettingsModel(SettingsModel):
    auto_start_bot: StrictBool = False
    operation_mode: OperationMode = "always_on"


class InterfaceSettingsModel(SettingsModel):
    language: InterfaceLanguage = DEFAULT_INTERFACE_LANGUAGE


class AIFlagsModel(SettingsModel):
    memory_enabled: StrictBool = AI_MEMORY_ENABLED
    setup_guide_dismissed: StrictBool = False
    setup_guide_ai_skipped: StrictBool = False


class AIMemoryLimitsModel(SettingsModel):
    history_max_entries: Annotated[StrictInt, Field(ge=1, le=500)] = AI_HISTORY_MAX_ENTRIES
    context_max_entries: Annotated[StrictInt, Field(ge=1, le=50)] = AI_CONTEXT_MAX_ENTRIES

    @model_validator(mode="after")
    def context_limit(self):
        if self.context_max_entries > self.history_max_entries:
            raise UserError("validation.maximum", field="context_max_entries", limit=str(self.history_max_entries))
        return self


def _memory_limits(stored, context):
    item = parse(AIMemoryLimitsModel, dict(history_max_entries=stored, context_max_entries=context))
    return item.history_max_entries, item.context_max_entries


class AISettingsModel(AIMemoryLimitsModel, AIFlagsModel):
    selected_model: StrictStr | None = None
    fallback_model: StrictStr | None = None
    provider: Literal["gemini", "deepseek", "openai"] | None = None
    deepseek_selected_model: StrictStr | None = None
    deepseek_fallback_model: StrictStr | None = None
    openai_selected_model: StrictStr | None = None
    openai_fallback_model: StrictStr | None = None
    cooldown_bypass_user_id: StrictStr | None = None
    response_language: ResponseLanguageSettings
    setup: AISetup | None = None


def _ai_settings(**values):
    item = parse(AISettingsModel, values)
    return AISettings(**{name: getattr(item, name) for name in AISettingsModel.model_fields})


TrimmedText = Annotated[StrictStr, StringConstraints(strip_whitespace=True, min_length=1)]
PresetId = Annotated[StrictStr, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
PresetName = Annotated[TrimmedText, Field(max_length=80)]


class TwitchTargetModel(SettingsModel):
    channel: Annotated[StrictStr,
        BeforeValidator(lambda value: value.strip().lower().removeprefix("#") if isinstance(value, str) else value),
        Field(min_length=1, max_length=100, pattern=r"^\S+$")]
    channel_user_id: Annotated[TrimmedText, Field(pattern=r"^\d+$")]


class TwitchIdentityModel(SettingsModel):
    client_id: Annotated[TrimmedText, Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")]
    bot_username: Annotated[TrimmedText, Field(pattern=r"^[A-Za-z0-9_]{1,25}$")]
    bot_user_id: Annotated[TrimmedText, Field(pattern=r"^[0-9]{1,20}$")]


class TwitchPresetModel(TwitchTargetModel):
    id: PresetId
    display_name: PresetName


def _recover_fields(model, section):
    values = {}
    for name, definition in model.model_fields.items():
        if name not in section:
            continue
        try:
            values[name] = field_value(definition.rebuild_annotation(), section[name], name)
        except ValueError:
            logger.warning("Ignoring invalid application setting name=%s", name)
    return model(**values).model_dump()


def validate_interface_language(language: object) -> str:
    return field_value(InterfaceLanguage, language, "language")


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
    try:
        return field_value(TrimmedText, value, field_name)
    except ValueError:
        logger.warning("Ignoring invalid application setting name=%s.%s", section_name, field_name)
        return None


def _validate_twitch_target(channel: object, channel_user_id: object) -> tuple[str, str]:
    item = parse(TwitchTargetModel, dict(channel=channel, channel_user_id=channel_user_id))
    return item.channel, item.channel_user_id


def _validate_preset_id(preset_id: object) -> str:
    return field_value(PresetId, preset_id, "id")


def validate_twitch_identity(client_id: object, bot_username: object, bot_user_id: object) -> tuple[str, str, str]:
    item = parse(TwitchIdentityModel, dict(client_id=client_id, bot_username=bot_username, bot_user_id=bot_user_id))
    return item.client_id, item.bot_username.lower(), item.bot_user_id


def _validate_preset_name(display_name: object) -> str:
    return field_value(PresetName, display_name, "display_name")


class TwitchSettingsModel(TwitchTargetModel):
    presets: tuple[TwitchConnectionPreset, ...] = ()
    selected_preset_id: PresetId | None = None

    @model_validator(mode="after")
    def selected_target(self):
        if self.selected_preset_id is not None:
            selected = next((preset for preset in self.presets if preset.id == self.selected_preset_id), None)
            if selected is None:
                raise UserError("app_settings.unknown_twitch_connection_preset")
            if (selected.channel, selected.channel_user_id) != (self.channel, self.channel_user_id):
                raise UserError("app_settings.selected_twitch_preset_does_not_match")
        return self


def validate_twitch_settings(
    channel: object, channel_user_id: object, *,
    presets: tuple[TwitchConnectionPreset, ...] = (), selected_preset_id: object = None,
) -> TwitchSettings:
    item = parse(TwitchSettingsModel, dict(channel=channel, channel_user_id=channel_user_id,
                                          presets=presets, selected_preset_id=selected_preset_id))
    return TwitchSettings(channel=item.channel, channel_user_id=item.channel_user_id,
                          presets=item.presets, selected_preset_id=item.selected_preset_id)


def _read_twitch_presets(section: dict[str, object]) -> tuple[TwitchConnectionPreset, ...]:
    payload = section.get("presets", [])
    if not isinstance(payload, list):
        logger.warning("Ignoring malformed application setting name=twitch.presets")
        return ()

    presets: list[TwitchConnectionPreset] = []
    known_ids: set[str] = set()
    known_names: set[str] = set()
    for item in payload:
        try:
            preset = parse(TwitchPresetModel, item)
        except ValueError:
            logger.warning("Ignoring invalid Twitch connection preset")
            continue
        normalized_name = preset.display_name.casefold()
        if preset.id in known_ids or normalized_name in known_names:
            logger.warning("Ignoring duplicate Twitch connection preset")
            continue
        known_ids.add(preset.id)
        known_names.add(normalized_name)
        presets.append(TwitchConnectionPreset(**preset.model_dump()))
    return tuple(presets)


def _read_models(section, provider):
    prefix = "" if provider == "gemini" else provider + "_"
    values = tuple(_read_optional_string(section, "ai", prefix + key) if provider == "gemini"
                   else section.get(prefix + key) for key in ("selected_model", "fallback_model"))
    if any(value is not None for value in values):
        try:
            return validate_provider_models(provider, *values)
        except ValueError:
            logger.warning("Ignoring invalid %s model settings override", provider)
    return None, None


def load_app_settings(section: ConfigSection) -> AppSettings:
    defaults = AppSettings()
    unsafe_defaults = replace(defaults, startup=StartupSettings(operation_mode="disabled"))
    try:
        payload = section.load()
    except FileNotFoundError:
        return defaults
    except (OSError, UnicodeError, ValueError) as error:
        logger.warning(
            "Could not load desktop settings path=%s error=%s; using defaults",
            section.path,
            type(error).__name__,
        )
        return unsafe_defaults
    if not isinstance(payload, dict):
        logger.warning("Application settings file must contain a JSON object; using defaults")
        return unsafe_defaults

    if type(payload.get("version")) is not int or payload["version"] != APP_SETTINGS_VERSION:
        logger.warning(
            "Unsupported application settings version=%r; using defaults",
            payload.get("version"),
        )
        return unsafe_defaults
    window_payload = _read_section(payload, "window")
    startup_payload = _read_section(payload, "startup")
    ai_payload = _read_section(payload, "ai")
    interface_payload = _read_section(payload, "interface")
    interface_language = interface_payload.get("language", DEFAULT_INTERFACE_LANGUAGE)
    if interface_language not in INTERFACE_LANGUAGES:
        logger.warning("Ignoring invalid application setting name=interface.language")
        interface_language = DEFAULT_INTERFACE_LANGUAGE
    operation_mode = startup_payload.get("operation_mode", "always_on")
    if (("startup" in payload and not isinstance(payload["startup"], dict))
            or not isinstance(operation_mode, str) or operation_mode not in OPERATION_MODES):
        logger.warning("Invalid headless operation mode; keeping Twitch disabled")
        operation_mode = "disabled"
    twitch_payload = _read_section(payload, "twitch")
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

    selected_model, fallback_model = _read_models(ai_payload, "gemini")
    cooldown_bypass_user_id = _read_optional_string(ai_payload, "ai", "cooldown_bypass_user_id")
    if cooldown_bypass_user_id is not None and re.fullmatch(r"[0-9]+", cooldown_bypass_user_id) is None:
        logger.warning("Ignoring invalid application setting name=ai.cooldown_bypass_user_id")
        cooldown_bypass_user_id = None
    response_language = ResponseLanguageSettings()
    try:
        provider = validate_ai_provider(ai_payload["provider"]) if ai_payload.get("provider") is not None else None
    except ValueError:
        logger.warning("Ignoring invalid AI provider selection")
        provider = None
    deepseek_selected, deepseek_fallback = _read_models(ai_payload, "deepseek")
    openai_selected, openai_fallback = _read_models(ai_payload, "openai")
    if "response_language" in ai_payload:
        language_payload = ai_payload["response_language"]
        try:
            if not isinstance(language_payload, dict):
                raise UserError("app_settings.response_language_settings_must_be_an_object")
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
        history_limit, context_limit = _memory_limits(ai_payload.get("history_max_entries", AI_HISTORY_MAX_ENTRIES),
                                                             ai_payload.get("context_max_entries", AI_CONTEXT_MAX_ENTRIES))
    except ValueError:
        # Reject invalid policy rather than silently expanding a requested cap.
        raise UserError("app_settings.invalid_saved_ai_history_context_limits_correct_profile_settings") from None
    return AppSettings(
        window=WindowSettings(**_recover_fields(WindowSettingsModel, window_payload)),
        startup=StartupSettings(**{**_recover_fields(StartupSettingsModel, startup_payload), "operation_mode": operation_mode}),
        ai=_ai_settings(
            history_max_entries=history_limit,
            context_max_entries=context_limit,
            **_recover_fields(AIFlagsModel, ai_payload),
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
        ),
        twitch=twitch,
        interface=InterfaceSettings(language=str(interface_language)),
    )


def save_app_settings(
    section: ConfigSection, settings: AppSettings, *, recovered_settings: AppSettings | None = None,
) -> None:
    section.save(
        {"version": APP_SETTINGS_VERSION, **asdict(settings)},
        recovered=None if recovered_settings is None else {"version": APP_SETTINGS_VERSION, **asdict(recovered_settings)},
        version=APP_SETTINGS_VERSION,
    )


def _has_saved_interface_language(section: ConfigSection) -> bool:
    """True when the settings already record a valid interface language."""
    try:
        payload = section.load()
    except (OSError, UnicodeError, ValueError):
        return False
    interface = payload.get("interface") if isinstance(payload, dict) else None
    return isinstance(interface, dict) and interface.get("language") in INTERFACE_LANGUAGES


class AppSettingsStore:
    def __init__(self, config: ConfigFile) -> None:
        self._section = config.section("app")
        self._lock = RLock()
        self._settings = load_app_settings(self._section)
        self._interface_language_saved = _has_saved_interface_language(self._section)

    def snapshot(self) -> AppSettings:
        with self._lock:
            return self._settings

    def update_operation_mode(self, mode: object) -> AppSettings:
        mode = field_value(OperationMode, mode, "operation_mode")
        with self._lock:
            updated = replace(self._settings, startup=replace(self._settings.startup, operation_mode=mode))
            save_app_settings(self._section, updated, recovered_settings=self._settings)
            self._settings = updated
        return updated

    def update_interface_language(self, language: object) -> AppSettings:
        parsed = validate_interface_language(language)
        with self._lock:
            if self._settings.interface.language == parsed and self._interface_language_saved:
                return self._settings
            updated = replace(self._settings, interface=InterfaceSettings(language=parsed))
            save_app_settings(self._section, updated, recovered_settings=self._settings)
            self._settings = updated
            self._interface_language_saved = True
        return updated

    def seed_interface_language(self, language: object) -> bool:
        """Apply the installer's language once, only while no language has been saved."""
        with self._lock:
            if self._interface_language_saved or language not in INTERFACE_LANGUAGES:
                return False
            parsed = validate_interface_language(language)
            updated = replace(self._settings, interface=InterfaceSettings(language=parsed))
            save_app_settings(self._section, updated, recovered_settings=self._settings)
            self._settings = updated
            self._interface_language_saved = True
        return True

    def update_desktop(
        self,
        *,
        start_minimized: object,
        minimize_to_tray: object,
        close_to_tray: object,
        auto_start_bot: object,
    ) -> AppSettings:
        window = parse(WindowSettingsModel, dict(start_minimized=start_minimized,
            minimize_to_tray=minimize_to_tray, close_to_tray=close_to_tray))
        auto_start_bot = field_value(StrictBool, auto_start_bot, "auto_start_bot")
        with self._lock:
            updated = replace(
                self._settings,
                window=WindowSettings(**window.model_dump()),
                startup=replace(self._settings.startup, auto_start_bot=auto_start_bot),
                ai=self._settings.ai,
                twitch=self._settings.twitch,
            )
            save_app_settings(self._section, updated, recovered_settings=self._settings)
            self._settings = updated
        return updated

    def update_ai_memory_limits(self, *, stored: object, context: object) -> AppSettings:
        stored, context = _memory_limits(stored, context)
        with self._lock:
            updated = replace(self._settings, ai=replace(self._settings.ai,
                              history_max_entries=stored, context_max_entries=context))
            save_app_settings(self._section, updated, recovered_settings=self._settings)
            self._settings = updated
        return updated

    def update_ai_memory(self, *, enabled: object) -> AppSettings:
        enabled = field_value(StrictBool, enabled, "memory_enabled")
        with self._lock:
            updated = replace(
                self._settings,
                window=self._settings.window,
                startup=self._settings.startup,
                ai=replace(self._settings.ai, memory_enabled=enabled),
                twitch=self._settings.twitch,
            )
            save_app_settings(self._section, updated, recovered_settings=self._settings)
            self._settings = updated
        return updated

    def update_ai_setup(self, payload: object) -> AppSettings:
        setup = parse_ai_setup(payload)
        with self._lock:
            updated = replace(self._settings, ai=replace(self._settings.ai, setup=setup,
                                                       provider=setup.primary.provider))
            save_app_settings(self._section, updated, recovered_settings=self._settings)
            self._settings = updated
        return updated

    def update_setup_guide(self, dismissed: object, ai_skipped: object) -> AppSettings:
        dismissed = field_value(StrictBool, dismissed, "setup_guide_dismissed")
        ai_skipped = field_value(StrictBool, ai_skipped, "setup_guide_ai_skipped")
        with self._lock:
            updated = replace(self._settings, ai=replace(self._settings.ai,
                              setup_guide_dismissed=dismissed, setup_guide_ai_skipped=ai_skipped))
            save_app_settings(self._section, updated, recovered_settings=self._settings)
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
            save_app_settings(self._section, updated, recovered_settings=self._settings)
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
            updated = replace(
                self._settings,
                window=self._settings.window,
                startup=self._settings.startup,
                ai=self._settings.ai,
                twitch=twitch,
            )
            save_app_settings(self._section, updated, recovered_settings=self._settings)
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
                    raise UserError("app_settings.unknown_twitch_connection_preset")
            if any(
                preset.id != parsed_id
                and preset.display_name.casefold() == parsed_name.casefold()
                for preset in existing
            ):
                raise UserError("app_settings.twitch_preset_name_already_exists")
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
            updated = replace(
                self._settings,
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
            save_app_settings(self._section, updated, recovered_settings=self._settings)
            self._settings = updated
        return updated, preset

    def delete_twitch_preset(self, preset_id: object) -> AppSettings:
        parsed_id = _validate_preset_id(preset_id)
        with self._lock:
            current = self._settings.twitch
            if not any(preset.id == parsed_id for preset in current.presets):
                raise UserError("app_settings.unknown_twitch_connection_preset")
            updated = replace(
                self._settings,
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
            save_app_settings(self._section, updated, recovered_settings=self._settings)
            self._settings = updated
        return updated
