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
    validate_personality_name,
    validate_personality_prompt,
    validate_profile_instructions,
)
from app.twitch.permissions import Permission
from app.utils.cooldown import CooldownPolicy
from app.config.ai import AI_MEMORY_ENABLED
from app.config.personalities import ACTIVE_AI_PERSONALITY


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
        self._persisted_profile_instructions = personality_settings.profile_instructions
        self._profile_instructions = personality_settings.profile_instructions
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
            save_command_overrides(
                self._command_settings_path, overrides,
                recovered_overrides=self._persisted_command_overrides,
            )
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
                save_command_overrides(
                    self._command_settings_path, overrides,
                    recovered_overrides=self._persisted_command_overrides,
                )
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
        with self._lock:
            self.get_ai_personality_prompt(personality)
            self._active_ai_personality = personality

    def save_active_ai_personality(self, personality: str) -> None:
        """Persist selection independently of prompt edits and profile instructions."""
        with self._lock:
            self.get_ai_personality_prompt(personality)
            if (
                personality not in AI_PERSONALITY_PROMPTS
                and personality not in self._persisted_personality_overrides
            ):
                raise ValueError("Save the custom personality before setting it active.")
            self._save_personality_settings(personality, self._persisted_personality_overrides)
            self._persisted_active_ai_personality = personality
            self._active_ai_personality = personality

    def get_active_ai_instructions(self) -> tuple[str, str, str]:
        """Read request instructions together so rename/delete cannot invalidate the name."""
        with self._lock:
            name = self._active_ai_personality
            return name, self._personality_prompts[name], self._profile_instructions

    def get_personality_settings_snapshot(self) -> tuple[PersonalitySettings, PersonalitySettings]:
        """Return effective prompts and persisted settings together for the editor."""
        with self._lock:
            return (
                PersonalitySettings(
                    self._active_ai_personality, dict(self._personality_prompts), self._profile_instructions,
                ),
                PersonalitySettings(
                    self._persisted_active_ai_personality, dict(self._persisted_personality_overrides),
                    self._persisted_profile_instructions,
                ),
            )

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
        personality = validate_personality_name(personality)
        with self._lock:
            self._personality_prompts[personality] = parsed_prompt
            self._active_ai_personality = personality

    def save_ai_personality(self, personality: str, prompt: object) -> None:
        parsed_prompt = validate_personality_prompt(prompt)
        with self._lock:
            self.get_ai_personality_prompt(personality)
            built_in_prompt = AI_PERSONALITY_PROMPTS.get(personality)
            overrides = dict(self._persisted_personality_overrides)
            if personality in AI_PERSONALITY_PROMPTS and parsed_prompt == built_in_prompt:
                overrides.pop(personality, None)
            else:
                overrides[personality] = parsed_prompt
            self._save_personality_settings(self._persisted_active_ai_personality, overrides)
            self._persisted_personality_overrides = overrides
            self._personality_prompts[personality] = parsed_prompt

    def _validate_new_personality_name(self, name: object) -> str:
        name = validate_personality_name(name)
        if any(existing.casefold() == name.casefold() for existing in self._personality_prompts):
            raise ValueError("A personality with that name already exists.")
        return name

    def create_ai_personality(self, name: object, prompt: object) -> str:
        parsed_prompt = validate_personality_prompt(prompt)
        with self._lock:
            name = self._validate_new_personality_name(name)
            overrides = {**self._persisted_personality_overrides, name: parsed_prompt}
            self._save_personality_settings(self._persisted_active_ai_personality, overrides)
            self._persisted_personality_overrides = overrides
            self._personality_prompts[name] = parsed_prompt
            return name

    def _require_custom_personality(self, name: str) -> str:
        prompt = self.get_ai_personality_prompt(name)
        if name in AI_PERSONALITY_PROMPTS:
            raise ValueError("Built-in personalities cannot be renamed or deleted.")
        return prompt

    def rename_ai_personality(self, personality: str, name: object) -> str:
        with self._lock:
            prompt = self._require_custom_personality(personality)
            name = self._validate_new_personality_name(name)
            overrides = dict(self._persisted_personality_overrides)
            overrides.pop(personality, None)
            overrides[name] = prompt
            saved_active = self._persisted_active_ai_personality
            if personality in (saved_active, self._active_ai_personality):
                saved_active = name
            self._save_personality_settings(saved_active, overrides)
            self._persisted_personality_overrides = overrides
            self._persisted_active_ai_personality = saved_active
            del self._personality_prompts[personality]
            self._personality_prompts[name] = prompt
            if self._active_ai_personality == personality:
                self._active_ai_personality = name
            return name

    def delete_ai_personality(self, personality: str) -> None:
        with self._lock:
            self._require_custom_personality(personality)
            overrides = dict(self._persisted_personality_overrides)
            overrides.pop(personality, None)
            saved_active = self._persisted_active_ai_personality
            if personality in (saved_active, self._active_ai_personality):
                saved_active = "neutral"
            self._save_personality_settings(saved_active, overrides)
            self._persisted_personality_overrides = overrides
            self._persisted_active_ai_personality = saved_active
            del self._personality_prompts[personality]
            if self._active_ai_personality == personality:
                self._active_ai_personality = "neutral"

    def reset_ai_personality(self, personality: str) -> None:
        with self._lock:
            built_in_prompt = self.get_builtin_ai_personality_prompt(personality)
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

    def _save_personality_settings(
        self,
        active_personality: str,
        overrides: dict[str, str],
        profile_instructions: str | None = None,
    ) -> None:
        if self._personality_settings_path is None:
            raise RuntimeError("Personality settings persistence is not configured.")
        save_personality_settings(
            self._personality_settings_path,
            PersonalitySettings(
                active_personality, overrides,
                self._persisted_profile_instructions if profile_instructions is None else profile_instructions,
            ),
            recovered_settings=PersonalitySettings(
                self._persisted_active_ai_personality, self._persisted_personality_overrides,
                self._persisted_profile_instructions,
            ),
        )

    @property
    def profile_instructions(self) -> str:
        with self._lock:
            return self._profile_instructions

    @property
    def profile_instructions_are_saved(self) -> bool:
        with self._lock:
            return self._profile_instructions == self._persisted_profile_instructions

    def apply_profile_instructions(self, instructions: object) -> None:
        parsed = validate_profile_instructions(instructions)
        with self._lock:
            self._profile_instructions = parsed

    def save_profile_instructions(self, instructions: object) -> None:
        parsed = validate_profile_instructions(instructions)
        with self._lock:
            self._save_personality_settings(
                self._persisted_active_ai_personality,
                self._persisted_personality_overrides,
                parsed,
            )
            self._persisted_profile_instructions = parsed
            self._profile_instructions = parsed

    def reset_profile_instructions(self) -> None:
        self.save_profile_instructions("")

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
