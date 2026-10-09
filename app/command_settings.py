"""Command-specific runtime settings and local JSON persistence."""

from __future__ import annotations

import json
import logging
import math
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.twitch.permissions import Permission
from app.settings_recovery import migrate_settings_key, preserve_settings_recovery
from app.utils.cooldown import CooldownPolicy

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CommandSettings:
    """Effective settings used to dispatch one registered command."""

    enabled: bool
    cooldown: CooldownPolicy
    permission: Permission

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise TypeError("Command enabled setting must be a boolean.")
        if not isinstance(self.cooldown, CooldownPolicy):
            raise TypeError("Command cooldown setting must be a CooldownPolicy.")
        if not isinstance(self.permission, Permission):
            raise TypeError("Command permission setting must be a Permission.")


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

    @property
    def is_empty(self) -> bool:
        return self.enabled is None and self.cooldown is None and self.permission is None

    def apply(self, defaults: CommandSettings) -> CommandSettings:
        return CommandSettings(
            enabled=defaults.enabled if self.enabled is None else self.enabled,
            cooldown=defaults.cooldown if self.cooldown is None else self.cooldown,
            permission=defaults.permission if self.permission is None else self.permission,
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

    if "fate" in defaults:
        payload = migrate_settings_key(path, payload, "forecast", "fate")

    overrides: dict[str, CommandSettingsOverride] = {}
    for command_name, raw_override in payload.items():
        if command_name not in defaults:
            logger.warning("Ignoring settings for unknown command name=%r", command_name)
            continue
        if not isinstance(raw_override, dict):
            logger.warning("Ignoring malformed settings for command name=%s", command_name)
            continue

        override = _parse_override(command_name, raw_override, defaults[command_name])
        if not override.is_empty:
            overrides[command_name] = override
    return overrides


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
    enabled = None
    if "enabled" in raw_override:
        raw_enabled = raw_override["enabled"]
        if type(raw_enabled) is bool:
            enabled = raw_enabled
        else:
            logger.warning("Ignoring invalid enabled setting for command name=%s", command_name)

    permission = None
    if "permission" in raw_override:
        raw_permission = raw_override["permission"]
        if isinstance(raw_permission, str):
            try:
                permission = Permission[raw_permission]
            except KeyError:
                pass
        if permission is None:
            logger.warning("Ignoring invalid permission setting for command name=%s", command_name)

    cooldown = None
    if "cooldown" in raw_override:
        cooldown = _parse_cooldown(command_name, raw_override["cooldown"], defaults.cooldown)

    return CommandSettingsOverride(
        enabled=enabled,
        cooldown=cooldown,
        permission=permission,
    )


def _parse_cooldown(
    command_name: str,
    raw_cooldown: object,
    defaults: CooldownPolicy,
) -> CooldownPolicy | None:
    if not isinstance(raw_cooldown, dict):
        logger.warning("Ignoring invalid cooldown setting for command name=%s", command_name)
        return None

    values = {
        "per_user_seconds": defaults.per_user_seconds,
        "global_seconds": defaults.global_seconds,
    }
    has_valid_value = False
    for field_name in values:
        if field_name not in raw_cooldown:
            continue
        parsed_value = _non_negative_number(raw_cooldown[field_name])
        if parsed_value is None:
            logger.warning(
                "Ignoring invalid cooldown field=%s for command name=%s",
                field_name,
                command_name,
            )
            continue
        values[field_name] = parsed_value
        has_valid_value = True

    if not has_valid_value:
        return None
    return CooldownPolicy(**values)


def _non_negative_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0:
        return None
    return number
