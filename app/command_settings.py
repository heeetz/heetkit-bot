"""Command-specific runtime settings and local JSON persistence."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Annotated, Any, Protocol
from pydantic import AfterValidator, Field, StrictBool, StrictStr
from app.settings_models import (SettingsModel, CommandName, StreamAvailability, SendAs, BurstInterval,
    EntryLimit, NonNegativeSeconds, ControlFree, PermissionName, field_value, parse)

from app.errors import UserError
from app.config.commands import BURST_HARD_MAX_COUNT, TG_DEFAULT_MAX_COUNT
from app.twitch.permissions import Permission
from app.settings_recovery import preserve_settings_recovery
from app.utils.cooldown import CooldownPolicy
from app.utils.text import validate_chat_template

logger = logging.getLogger(__name__)
LEADERBOARD_TEMPLATES = {"top": "Monthly top: {entries}", "rank": "{sender}, you’re #{place} this month with {messages} messages."}
LEADERBOARD_VARIABLES = {"top": ("entries",), "rank": ("place", "messages")}


def validate_entry_limit(value):
    return field_value(EntryLimit, value, "entry_limit")


def validate_leaderboard_template(name, value):
    return validate_chat_template(value, required=LEADERBOARD_VARIABLES[name], optional=("sender",))


class CommandNameConflict(UserError):
    def __init__(self, name: str) -> None:
        super().__init__("custom_commands.command_name_alias_already_exists", name=name)


BurstMaxCount = Annotated[int, Field(strict=True, ge=1, le=BURST_HARD_MAX_COUNT)]
DisplayName = Annotated[ControlFree, Field(max_length=80), AfterValidator(str.strip)]


def _unique_aliases(values):
    if len(set(values)) != len(values):
        raise UserError("command_settings.command_aliases_unique")
    return values


CommandAliases = Annotated[tuple[CommandName, ...], Field(max_length=10), AfterValidator(_unique_aliases)]


class CommandOverrideModel(SettingsModel):
    enabled: StrictBool | None = None
    permission: PermissionName | None = None
    aliases: CommandAliases | None = None
    display_name: DisplayName | None = None
    removed: StrictBool | None = None
    burst_interval_ms: BurstInterval | None = None
    burst_max_count: BurstMaxCount | None = None
    stream_availability: StreamAvailability | None = None
    primary_name: CommandName | None = None
    send_as: SendAs | None = None
    entry_limit: EntryLimit | None = None
    chat_template: StrictStr | None = None


def validate_primary_name(value: object) -> str:
    return field_value(CommandName, value, "primary_name")


def validate_stream_availability(value: object) -> str:
    return field_value(StreamAvailability, value, "stream_availability")


def validate_send_as(value: object) -> str:
    return field_value(SendAs, value, "send_as")


def validate_burst_max_count(value: object) -> int:
    return field_value(BurstMaxCount, value, "burst_max_count")


def validate_burst_interval(value: object) -> int:
    return field_value(BurstInterval, value, "burst_interval_ms")


def validate_command_aliases(value: object) -> tuple[str, ...]:
    return field_value(CommandAliases, value, "aliases")


def validate_display_name(value: object) -> str:
    return field_value(DisplayName, value, "display_name")


@dataclass(frozen=True, slots=True)
class CommandSettings:
    """Effective settings used to dispatch one registered command."""

    enabled: bool
    cooldown: CooldownPolicy
    permission: Permission
    aliases: tuple[str, ...] = ()
    display_name: str = ""
    removed: bool = False
    burst_interval_ms: int = 0
    burst_max_count: int = TG_DEFAULT_MAX_COUNT
    stream_availability: str = "anytime"
    primary_name: str = ""
    send_as: str | None = None
    entry_limit: int | None = None
    chat_template: str | None = None

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise UserError("command_settings.command_enabled_setting_must_be_a_boolean")
        if not isinstance(self.cooldown, CooldownPolicy):
            raise UserError("command_settings.command_cooldown_setting_must_be_a_cooldownpolicy")
        if not isinstance(self.permission, Permission):
            raise UserError("command_settings.command_permission_setting_must_be_a_permission")
        if type(self.removed) is not bool:
            raise UserError("command_settings.command_removed_setting_must_be_a_boolean")
        if not isinstance(self.aliases, tuple) or validate_command_aliases(self.aliases) != self.aliases:
            raise UserError("command_settings.command_aliases_must_be_normalized_unique_names")
        if validate_display_name(self.display_name) != self.display_name:
            raise UserError("command_settings.display_name_must_not_have_surrounding_whitespace")
        validate_burst_interval(self.burst_interval_ms)
        validate_burst_max_count(self.burst_max_count)
        validate_stream_availability(self.stream_availability)
        if self.send_as is not None:
            validate_send_as(self.send_as)
        if self.primary_name and validate_primary_name(self.primary_name) != self.primary_name:
            raise UserError("command_settings.command_name_must_be_normalized")
        if not isinstance(self.primary_name, str):
            raise UserError("command_settings.command_name_must_be_text")
        if self.entry_limit is not None:
            validate_entry_limit(self.entry_limit)


class CommandSettingsDefinition(Protocol):
    """Registry metadata required to initialize command settings."""

    name: str

    @property
    def default_settings(self) -> CommandSettings: ...


@dataclass(frozen=True, slots=True)
class CommandSettingsOverride:
    enabled: bool | None = None
    cooldown: CooldownPolicy | None = None
    permission: Permission | None = None
    aliases: tuple[str, ...] | None = None
    display_name: str | None = None
    removed: bool | None = None
    burst_interval_ms: int | None = None
    burst_max_count: int | None = None
    stream_availability: str | None = None
    primary_name: str | None = None
    send_as: str | None = None
    entry_limit: int | None = None
    chat_template: str | None = None

    @property
    def is_empty(self) -> bool:
        return all(value is None for value in (self.enabled, self.cooldown, self.permission,
                   self.aliases, self.display_name, self.removed, self.burst_interval_ms, self.burst_max_count,
                   self.stream_availability, self.primary_name, self.send_as, self.entry_limit, self.chat_template))

    def apply(self, defaults: CommandSettings) -> CommandSettings:
        return CommandSettings(
            enabled=defaults.enabled if self.enabled is None else self.enabled,
            cooldown=defaults.cooldown if self.cooldown is None else self.cooldown,
            permission=defaults.permission if self.permission is None else self.permission,
            aliases=defaults.aliases if self.aliases is None else self.aliases,
            display_name=defaults.display_name if self.display_name is None else self.display_name,
            removed=defaults.removed if self.removed is None else self.removed,
            burst_interval_ms=defaults.burst_interval_ms if self.burst_interval_ms is None else self.burst_interval_ms,
            burst_max_count=defaults.burst_max_count if self.burst_max_count is None else self.burst_max_count,
            stream_availability=defaults.stream_availability if self.stream_availability is None else self.stream_availability,
            primary_name=defaults.primary_name if self.primary_name is None else self.primary_name,
            send_as=defaults.send_as if self.send_as is None else self.send_as,
            entry_limit=defaults.entry_limit if self.entry_limit is None else self.entry_limit,
            chat_template=defaults.chat_template if self.chat_template is None else self.chat_template,
        )

    @classmethod
    def from_settings(
        cls,
        settings: CommandSettings,
        defaults: CommandSettings,
    ) -> CommandSettingsOverride:
        return cls(
            enabled=settings.enabled if settings.enabled != defaults.enabled else None,
            cooldown=settings.cooldown if settings.cooldown != defaults.cooldown else None,
            permission=settings.permission if settings.permission != defaults.permission else None,
            aliases=settings.aliases if settings.aliases != defaults.aliases else None,
            display_name=settings.display_name if settings.display_name != defaults.display_name else None,
            removed=settings.removed if settings.removed != defaults.removed else None,
            burst_interval_ms=settings.burst_interval_ms if settings.burst_interval_ms != defaults.burst_interval_ms else None,
            burst_max_count=settings.burst_max_count if settings.burst_max_count != defaults.burst_max_count else None,
            stream_availability=settings.stream_availability if settings.stream_availability != defaults.stream_availability else None,
            primary_name=settings.primary_name if settings.primary_name != defaults.primary_name else None,
            send_as=settings.send_as if settings.send_as != defaults.send_as else None,
            entry_limit=settings.entry_limit if settings.entry_limit != defaults.entry_limit else None,
            chat_template=settings.chat_template if settings.chat_template != defaults.chat_template else None,
        )

    def to_json(self) -> dict[str, object]:
        result: dict[str, object] = {}
        if self.enabled is not None:
            result["enabled"] = self.enabled
        if self.cooldown is not None:
            result["cooldown"] = {
                "per_user_seconds": self.cooldown.per_user_seconds,
                "global_seconds": self.cooldown.global_seconds,
            }
        if self.permission is not None:
            result["permission"] = self.permission.name
        if self.aliases is not None:
            result["aliases"] = list(self.aliases)
        for key in ("display_name", "removed", "burst_interval_ms", "burst_max_count", "stream_availability", "primary_name", "send_as",
                    "entry_limit", "chat_template"):
            value = getattr(self, key)
            if value is not None:
                result[key] = value
        return result


def load_command_overrides(
    path: Path,
    defaults: Mapping[str, CommandSettings],
) -> dict[str, CommandSettingsOverride]:
    """Load valid overrides without allowing local file errors to block startup."""
    if not path.exists():
        return {}

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        logger.warning(
            "Could not load command settings file path=%s error=%s; using defaults",
            path,
            type(error).__name__,
        )
        return {}

    if not isinstance(payload, dict):
        logger.warning("Command settings file must contain a JSON object; using defaults")
        return {}

    overrides: dict[str, CommandSettingsOverride] = {}
    for command_name, raw_override in payload.items():
        old_commands = command_name == "commands" and "help" in defaults and command_name not in defaults
        if command_name not in defaults and not old_commands:
            logger.warning("Ignoring settings for unknown command name=%r", command_name)
            continue
        if not isinstance(raw_override, dict):
            logger.warning("Ignoring malformed settings for command name=%s", command_name)
            continue

        if old_commands:
            raw_override = {key: value for key, value in raw_override.items()
                            if key in {"enabled", "removed", "aliases", "primary_name"}}
        override = _parse_override(command_name, raw_override, defaults["help" if old_commands else command_name])
        if old_commands or not override.is_empty:
            overrides[command_name] = override
    return overrides


def merge_commands_into_help(
    help_settings: CommandSettings,
    old_commands: CommandSettings | CommandSettingsOverride,
    used_names: set[str],
) -> CommandSettings:
    aliases = tuple(alias for alias in help_settings.aliases if alias != "commands")
    if old_commands.enabled is not False and not old_commands.removed:
        used_names = used_names | {help_settings.primary_name}
        aliases = tuple(dict.fromkeys(("commands", *aliases, old_commands.primary_name,
                                       *(old_commands.aliases or ()))))
        aliases = tuple(alias for alias in aliases if alias and alias not in used_names)
        if len(aliases) > 10:
            logger.warning("Dropping %d aliases when merging !commands into !help (limit: 10)", len(aliases) - 10)
    return replace(help_settings, aliases=aliases[:10])


def save_command_overrides(
    path: Path,
    overrides: Mapping[str, CommandSettingsOverride],
    *,
    recovered_overrides: Mapping[str, CommandSettingsOverride] | None = None,
) -> None:
    """Atomically replace the local command override file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        command_name: override.to_json()
        for command_name, override in sorted(overrides.items())
        if not override.is_empty
    }
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
            json.dump(payload, temporary_file, indent=2, sort_keys=True)
            temporary_file.write("\n")
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        preserve_settings_recovery(
            path,
            None if recovered_overrides is None else {
                name: override.to_json() for name, override in recovered_overrides.items()
            },
        )
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _parse_override(
    command_name: str,
    raw_override: dict[str, Any],
    defaults: CommandSettings,
) -> CommandSettingsOverride:
    values = {}
    for key, definition in CommandOverrideModel.model_fields.items():
        if key not in raw_override or raw_override[key] is None:
            continue
        if key in {"entry_limit", "chat_template"} and getattr(defaults, key) is None:
            continue
        try:
            values[key] = field_value(definition.rebuild_annotation(), raw_override[key], key)
            if key == "chat_template":
                values[key] = validate_leaderboard_template(command_name, values[key])
        except ValueError:
            values.pop(key, None)
            logger.warning("Ignoring invalid %s setting for command name=%s", key, command_name)
    if "permission" in values:
        values["permission"] = Permission[values["permission"]]
    if "cooldown" in raw_override:
        values["cooldown"] = _parse_cooldown(command_name, raw_override["cooldown"], defaults.cooldown)
    return CommandSettingsOverride(**values)


class CooldownSettingsModel(SettingsModel):
    per_user_seconds: NonNegativeSeconds | None = None
    global_seconds: NonNegativeSeconds | None = None


def _parse_cooldown(command_name: str, raw_cooldown: object, defaults: CooldownPolicy) -> CooldownPolicy | None:
    if not isinstance(raw_cooldown, dict):
        logger.warning("Ignoring invalid cooldown setting for command name=%s", command_name)
        return None
    values = {}
    for name in CooldownSettingsModel.model_fields:
        if name in raw_cooldown:
            try:
                values[name] = field_value(NonNegativeSeconds, raw_cooldown[name], name)
            except ValueError:
                logger.warning("Ignoring invalid cooldown field=%s for command name=%s", name, command_name)
    if not values:
        return None
    return CooldownPolicy(**{name: values.get(name, getattr(defaults, name))
                             for name in CooldownSettingsModel.model_fields})
