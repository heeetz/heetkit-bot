"""Thread-safe runtime controls shared by the bot and local control panel."""

from collections.abc import Iterable
from pathlib import Path
from threading import RLock
from time import monotonic
from typing import Literal

from app.command_settings import (
    CommandSettings,
    CommandSettingsDefinition,
    CommandSettingsOverride,
    load_command_overrides,
    save_command_overrides,
)
from app.config.personalities import AI_PERSONALITY_PROMPTS
from app.personality_settings import (
    PersonalitySettings,
    load_personality_settings,
    save_personality_settings,
    validate_personality_prompt,
)
from app.twitch.permissions import Permission
from app.utils.cooldown import CooldownPolicy
from config import AI_MEMORY_ENABLED, ACTIVE_AI_PERSONALITY


TwitchConnectionState = Literal[
    "stopped", "connecting", "connected", "reconnecting", "auth_required", "failed"
]


class RuntimeState:
    def __init__(
        self,
        command_settings_path: str | Path | None = None,
        personality_settings_path: str | Path | None = None,
    ) -> None:
        self._lock = RLock()
        self._command_defaults: dict[str, CommandSettings] = {}
        self._command_settings: dict[str, CommandSettings] = {}
        self._persisted_command_overrides: dict[str, CommandSettingsOverride] = {}
        self._command_settings_path = (
            None if command_settings_path is None else Path(command_settings_path)
        )
        self._personality_settings_path = (
            None if personality_settings_path is None else Path(personality_settings_path)
        )
        self._ai_memory_enabled = AI_MEMORY_ENABLED
        personality_settings = (
            PersonalitySettings(ACTIVE_AI_PERSONALITY, {})
            if self._personality_settings_path is None
            else load_personality_settings(
                self._personality_settings_path,
                AI_PERSONALITY_PROMPTS,
                ACTIVE_AI_PERSONALITY,
            )
        )
        self._persisted_personality_overrides = dict(personality_settings.overrides)
        self._personality_prompts = dict(AI_PERSONALITY_PROMPTS)
        self._personality_prompts.update(self._persisted_personality_overrides)
        self._persisted_active_ai_personality = personality_settings.active_personality
        self._active_ai_personality = personality_settings.active_personality
        self._bot_running = False
        self._twitch_connection_state: TwitchConnectionState = "stopped"
        self._started_at: float | None = None
        self._uptime_started_at = monotonic()

    @property
    def available_personalities(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._personality_prompts)

    @property
    def runtime_toggleable_commands(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._command_settings)

    def configure_commands(self, definitions: Iterable[CommandSettingsDefinition]) -> None:
        with self._lock:
            self._command_defaults = {
                definition.name: definition.default_settings
                for definition in definitions
            }
            self._persisted_command_overrides = (
                {}
                if self._command_settings_path is None
                else load_command_overrides(
                    self._command_settings_path,
                    self._command_defaults,
                )
            )
            self._command_settings = {
                name: self._persisted_command_overrides.get(
                    name,
                    CommandSettingsOverride(),
                ).apply(defaults)
                for name, defaults in self._command_defaults.items()
            }

    def get_command_settings(self, command_name: str) -> CommandSettings:
        with self._lock:
            try:
                return self._command_settings[command_name]
            except KeyError as error:
                raise KeyError(f"Unknown command: {command_name}") from error

    def get_command_default_settings(self, command_name: str) -> CommandSettings:
        with self._lock:
            try:
                return self._command_defaults[command_name]
            except KeyError as error:
                raise KeyError(f"Unknown command: {command_name}") from error

    def command_settings_are_saved(self, command_name: str) -> bool:
        with self._lock:
            current = self.get_command_settings(command_name)
            defaults = self.get_command_default_settings(command_name)
            saved = self._persisted_command_overrides.get(
                command_name,
                CommandSettingsOverride(),
            ).apply(defaults)
            return current == saved

    def has_saved_command_override(self, command_name: str) -> bool:
        with self._lock:
            self.get_command_default_settings(command_name)
            return command_name in self._persisted_command_overrides

    def apply_command_settings(
        self,
        command_name: str,
        *,
        enabled: bool | None = None,
        cooldown: CooldownPolicy | None = None,
        permission: Permission | None = None,
    ) -> CommandSettings:
        with self._lock:
            current = self.get_command_settings(command_name)
            updated = CommandSettings(
                enabled=current.enabled if enabled is None else enabled,
                cooldown=current.cooldown if cooldown is None else cooldown,
                permission=current.permission if permission is None else permission,
            )
            self._command_settings[command_name] = updated
            return updated

    def save_command_override(self, command_name: str) -> None:
        with self._lock:
            current = self.get_command_settings(command_name)
            self._save_command_settings(command_name, current)

    def save_command_settings(
        self,
        command_name: str,
        *,
        enabled: bool,
        cooldown: CooldownPolicy,
        permission: Permission,
    ) -> CommandSettings:
        with self._lock:
            self.get_command_default_settings(command_name)
            updated = CommandSettings(
                enabled=enabled,
                cooldown=cooldown,
                permission=permission,
            )
            self._save_command_settings(command_name, updated)
            self._command_settings[command_name] = updated
            return updated

    def _save_command_settings(
        self,
        command_name: str,
        settings: CommandSettings,
    ) -> None:
        if self._command_settings_path is None:
            raise RuntimeError("Command settings persistence is not configured.")
        with self._lock:
            defaults = self._command_defaults[command_name]
            override = CommandSettingsOverride.from_settings(settings, defaults)
            overrides = dict(self._persisted_command_overrides)
            if override.is_empty:
                overrides.pop(command_name, None)
            else:
                overrides[command_name] = override
            save_command_overrides(self._command_settings_path, overrides)
            self._persisted_command_overrides = overrides

    def reset_command_settings(self, command_name: str) -> CommandSettings:
        with self._lock:
            try:
                defaults = self._command_defaults[command_name]
            except KeyError as error:
                raise KeyError(f"Unknown command: {command_name}") from error
            overrides = dict(self._persisted_command_overrides)
            overrides.pop(command_name, None)
            if self._command_settings_path is not None:
                save_command_overrides(self._command_settings_path, overrides)
            self._persisted_command_overrides = overrides
            self._command_settings[command_name] = defaults
            return defaults

    def is_command_enabled(self, command_name: str) -> bool:
        return self.command_enabled(command_name)

    def set_command_enabled(self, command_name: str, enabled: bool) -> None:
        with self._lock:
            if command_name in self._command_settings:
                self.apply_command_settings(command_name, enabled=enabled)

    def command_enabled(self, command_name: str) -> bool:
        with self._lock:
            settings = self._command_settings.get(command_name)
            return True if settings is None else settings.enabled

    @property
    def ai_enabled(self) -> bool:
        return self.command_enabled("ask")

    def set_ai_enabled(self, enabled: bool) -> None:
        self.set_command_enabled("ask", enabled)

    @property
    def ai_memory_enabled(self) -> bool:
        with self._lock:
            return self._ai_memory_enabled

    def set_ai_memory_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._ai_memory_enabled = enabled

    @property
    def active_ai_personality(self) -> str:
        with self._lock:
            return self._active_ai_personality

    def set_active_ai_personality(self, personality: str) -> None:
        if personality not in self.available_personalities:
            raise ValueError(f"Unknown AI personality: {personality}")
        with self._lock:
            self._active_ai_personality = personality

    def get_ai_personality_prompt(self, personality: str) -> str:
        with self._lock:
            try:
                return self._personality_prompts[personality]
            except KeyError as error:
                raise ValueError(f"Unknown AI personality: {personality}") from error

    def get_builtin_ai_personality_prompt(self, personality: str) -> str:
        self.get_ai_personality_prompt(personality)
        return AI_PERSONALITY_PROMPTS.get(personality, "")

    def personality_prompt_is_saved(self, personality: str) -> bool:
        with self._lock:
            current = self.get_ai_personality_prompt(personality)
            saved = self._persisted_personality_overrides.get(
                personality,
                self.get_builtin_ai_personality_prompt(personality),
            )
            return current == saved

    def has_saved_personality_override(self, personality: str) -> bool:
        with self._lock:
            self.get_builtin_ai_personality_prompt(personality)
            return personality in self._persisted_personality_overrides

    @property
    def active_ai_personality_is_saved(self) -> bool:
        with self._lock:
            return self._active_ai_personality == self._persisted_active_ai_personality

    def apply_ai_personality(self, personality: str, prompt: object) -> None:
        parsed_prompt = validate_personality_prompt(prompt)
        if not isinstance(personality, str) or not personality.strip() or len(personality) > 64:
            raise ValueError("Invalid AI personality name.")
        with self._lock:
            self._personality_prompts[personality] = parsed_prompt
            self._active_ai_personality = personality

    def save_ai_personality(self, personality: str, prompt: object) -> None:
        parsed_prompt = validate_personality_prompt(prompt)
        if not isinstance(personality, str) or not personality.strip() or len(personality) > 64:
            raise ValueError("Invalid AI personality name.")
        built_in_prompt = AI_PERSONALITY_PROMPTS.get(personality)
        with self._lock:
            overrides = dict(self._persisted_personality_overrides)
            if personality in AI_PERSONALITY_PROMPTS and parsed_prompt == built_in_prompt:
                overrides.pop(personality, None)
            else:
                overrides[personality] = parsed_prompt
            self._save_personality_settings(personality, overrides)
            self._persisted_personality_overrides = overrides
            self._persisted_active_ai_personality = personality
            self._personality_prompts[personality] = parsed_prompt
            self._active_ai_personality = personality

    def reset_ai_personality(self, personality: str) -> None:
        built_in_prompt = self.get_builtin_ai_personality_prompt(personality)
        with self._lock:
            overrides = dict(self._persisted_personality_overrides)
            if personality in AI_PERSONALITY_PROMPTS:
                overrides.pop(personality, None)
            else:
                overrides[personality] = built_in_prompt
            if self._personality_settings_path is not None:
                self._save_personality_settings(
                    self._persisted_active_ai_personality,
                    overrides,
                )
            self._persisted_personality_overrides = overrides
            self._personality_prompts[personality] = built_in_prompt
            self._active_ai_personality = personality

    def _save_personality_settings(
        self,
        active_personality: str,
        overrides: dict[str, str],
    ) -> None:
        if self._personality_settings_path is None:
            raise RuntimeError("Personality settings persistence is not configured.")
        save_personality_settings(
            self._personality_settings_path,
            PersonalitySettings(active_personality, overrides),
        )

    def set_bot_running(self, running: bool) -> None:
        with self._lock:
            self._bot_running = running
            self._started_at = monotonic() if running else None
            if running:
                self._twitch_connection_state = "connecting"
            elif self._twitch_connection_state not in ("auth_required", "failed"):
                self._twitch_connection_state = "stopped"

    @property
    def twitch_connected(self) -> bool:
        with self._lock:
            return self._twitch_connection_state == "connected"

    @property
    def twitch_connection_state(self) -> TwitchConnectionState:
        with self._lock:
            return self._twitch_connection_state

    def set_twitch_connection_state(self, state: TwitchConnectionState) -> None:
        with self._lock:
            self._twitch_connection_state = state

    def elapsed_seconds(self) -> int:
        with self._lock:
            return max(0, int(monotonic() - self._uptime_started_at))

    def status(self) -> tuple[bool, int]:
        with self._lock:
            if not self._bot_running or self._started_at is None:
                return False, 0
            return True, max(0, int(monotonic() - self._started_at))
