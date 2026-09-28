"""Thread-safe runtime controls shared by the bot and local control panel."""

from collections.abc import Iterable
from pathlib import Path
from threading import RLock
from time import monotonic

from app.command_settings import (
    CommandSettings,
    CommandSettingsDefinition,
    CommandSettingsOverride,
    load_command_overrides,
    save_command_overrides,
)
from app.config.personalities import AI_PERSONALITY_PRESETS
from app.twitch.permissions import Permission
from app.utils.cooldown import CooldownPolicy
from config import AI_MEMORY_ENABLED, ACTIVE_AI_PERSONALITY


class RuntimeState:
    def __init__(self, command_settings_path: str | Path | None = None) -> None:
        self._lock = RLock()
        self._command_defaults: dict[str, CommandSettings] = {}
        self._command_settings: dict[str, CommandSettings] = {}
        self._persisted_command_overrides: dict[str, CommandSettingsOverride] = {}
        self._command_settings_path = (
            None if command_settings_path is None else Path(command_settings_path)
        )
        self._ai_memory_enabled = AI_MEMORY_ENABLED
        self._active_ai_personality = ACTIVE_AI_PERSONALITY
        self._bot_running = False
        self._twitch_connected = False
        self._started_at: float | None = None
        self._uptime_started_at = monotonic()

    @property
    def available_personalities(self) -> tuple[str, ...]:
        return tuple(AI_PERSONALITY_PRESETS)

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
            if self._command_settings_path is None:
                raise RuntimeError("Command settings persistence is not configured.")
            current = self.get_command_settings(command_name)
            defaults = self._command_defaults[command_name]
            override = CommandSettingsOverride.from_settings(current, defaults)
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
        if personality not in AI_PERSONALITY_PRESETS:
            raise ValueError(f"Unknown AI personality: {personality}")
        with self._lock:
            self._active_ai_personality = personality

    def set_bot_running(self, running: bool) -> None:
        with self._lock:
            self._bot_running = running
            self._started_at = monotonic() if running else None
            if not running:
                self._twitch_connected = False

    @property
    def twitch_connected(self) -> bool:
        with self._lock:
            return self._twitch_connected

    def set_twitch_connected(self, connected: bool) -> None:
        with self._lock:
            self._twitch_connected = connected

    def elapsed_seconds(self) -> int:
        with self._lock:
            return max(0, int(monotonic() - self._uptime_started_at))

    def status(self) -> tuple[bool, int]:
        with self._lock:
            if not self._bot_running or self._started_at is None:
                return False, 0
            return True, max(0, int(monotonic() - self._started_at))
