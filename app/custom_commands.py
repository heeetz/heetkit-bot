"""Validated, non-executable local custom commands."""

from __future__ import annotations

import json
import logging
import math
import os
import random
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from uuid import UUID, uuid4

from app.twitch.permissions import Permission
from app.settings_recovery import preserve_settings_recovery
from app.utils.cooldown import CooldownPolicy
from app.utils.text import normalize_command_name


logger = logging.getLogger(__name__)
SCHEMA_VERSION = 1
MAX_RESPONSE_LENGTH = 450
MAX_POSITIONAL_ARGUMENTS = 9
VARIABLES = ("sender", "target", "args", *(f"arg{i}" for i in range(1, MAX_POSITIONAL_ARGUMENTS + 1)), "random_user")
_VARIABLE_PATTERN = re.compile(r"\{([^{}]+)\}")


@dataclass(frozen=True, slots=True)
class CustomCommand:
    id: str
    name: str
    enabled: bool
    responses: tuple[str, ...]
    permission: Permission
    cooldown: CooldownPolicy
    aliases: tuple[str, ...]

    @property
    def response_mode(self) -> str:
        return "random" if len(self.responses) > 1 else "single"

    def to_json(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "enabled": self.enabled,
            "responses": list(self.responses),
            "permission": self.permission.name,
            "per_user_seconds": self.cooldown.per_user_seconds,
            "global_seconds": self.cooldown.global_seconds,
            "aliases": list(self.aliases),
        }


def _name(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Command names and aliases must be text.")
    normalized = normalize_command_name(value)
    if not normalized or len(normalized) > 40 or any(char.isspace() or char in "!{}" for char in normalized):
        raise ValueError("Command names and aliases must be single words of at most 40 characters.")
    return normalized


def _cooldown(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0 or value > 86400 or not math.isfinite(float(value)):
        raise ValueError("Cooldowns must be numbers from 0 to 86400 seconds.")
    return float(value)


def _response(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 2000 or "\n" in value or "\r" in value:
        raise ValueError("Each response must be one non-empty line of at most 2000 characters.")
    variables = _VARIABLE_PATTERN.findall(value)
    if any(variable not in VARIABLES for variable in variables):
        raise ValueError("Response contains an unknown variable.")
    if "{" in _VARIABLE_PATTERN.sub("", value) or "}" in _VARIABLE_PATTERN.sub("", value):
        raise ValueError("Response has an invalid variable placeholder.")
    return value.strip()


def parse_custom_command(raw: object, *, command_id: str | None = None) -> CustomCommand:
    if not isinstance(raw, dict):
        raise ValueError("Custom command must be an object.")
    identifier = command_id if command_id is not None else raw.get("id")
    try:
        identifier = str(UUID(str(identifier)))
    except (ValueError, AttributeError) as error:
        raise ValueError("Custom command ID is invalid.") from error
    name = _name(raw.get("name"))
    enabled = raw.get("enabled")
    if type(enabled) is not bool:
        raise ValueError("Enabled must be a boolean.")
    responses = raw.get("responses")
    if not isinstance(responses, list) or not 1 <= len(responses) <= 10:
        raise ValueError("Provide 1 to 10 response templates.")
    parsed_responses = tuple(_response(response) for response in responses)
    permission = raw.get("permission")
    if not isinstance(permission, str) or permission not in Permission.__members__:
        raise ValueError("Permission must be a valid user level.")
    aliases = raw.get("aliases")
    if not isinstance(aliases, list) or len(aliases) > 10:
        raise ValueError("Provide at most 10 aliases.")
    parsed_aliases = tuple(_name(alias) for alias in aliases)
    if len({name, *parsed_aliases}) != 1 + len(parsed_aliases):
        raise ValueError("Command name and aliases must be unique.")
    return CustomCommand(
        id=identifier,
        name=name,
        enabled=enabled,
        responses=parsed_responses,
        permission=Permission[permission],
        cooldown=CooldownPolicy(
            per_user_seconds=_cooldown(raw.get("per_user_seconds")),
            global_seconds=_cooldown(raw.get("global_seconds")),
        ),
        aliases=parsed_aliases,
    )


def render_response(command: CustomCommand, arguments: str, sender: str, random_user: str,
                    *, template: str | None = None) -> str:
    parts = arguments.split()
    values = {"sender": sender, "target": (parts[0].lstrip("@") or sender) if parts else sender,
              "args": arguments, "random_user": random_user}
    values.update({f"arg{i}": parts[i - 1] if i <= len(parts) else "" for i in range(1, MAX_POSITIONAL_ARGUMENTS + 1)})
    template = template if template is not None else random.choice(command.responses)
    expanded = _VARIABLE_PATTERN.sub(lambda match: values[match.group(1)], template)
    return expanded.encode("utf-8")[:MAX_RESPONSE_LENGTH].decode("utf-8", errors="ignore").strip()


class CustomCommandStore:
    """Keep immutable command snapshots behind one lock; publish after atomic save."""

    def __init__(self, path: Path, built_in_names: set[str]) -> None:
        self._path = path
        self._built_in_names = built_in_names
        self._lock = RLock()
        self._commands: dict[str, CustomCommand] = {}
        self._lookup: dict[str, str] = {}
        self._load()

    def list(self) -> tuple[CustomCommand, ...]:
        with self._lock:
            return tuple(sorted(self._commands.values(), key=lambda command: command.name))

    def get_by_name(self, name: str) -> CustomCommand | None:
        with self._lock:
            return self._commands.get(self._lookup.get(normalize_command_name(name), ""))

    def save(self, raw: object) -> CustomCommand:
        if not isinstance(raw, dict):
            raise ValueError("Custom command must be an object.")
        with self._lock:
            requested_id = raw.get("id")
            if requested_id is not None and requested_id not in self._commands:
                raise ValueError("Unknown custom command ID.")
            command = parse_custom_command(raw, command_id=requested_id or str(uuid4()))
            updated = dict(self._commands)
            updated[command.id] = command
            self._validate_collisions(updated)
            self._write(updated)
            self._publish(updated)
            return command

    def delete(self, identifier: str) -> None:
        with self._lock:
            if identifier not in self._commands:
                raise ValueError("Unknown custom command ID.")
            updated = dict(self._commands)
            del updated[identifier]
            self._write(updated)
            self._publish(updated)

    def _validate_collisions(self, commands: dict[str, CustomCommand]) -> None:
        used = set(self._built_in_names)
        for command in commands.values():
            for name in (command.name, *command.aliases):
                if name in used:
                    raise ValueError(f"Command name or alias already exists: {name}")
                used.add(name)

    def _publish(self, commands: dict[str, CustomCommand]) -> None:
        self._commands = commands
        self._lookup = {name: command.id for command in commands.values() for name in (command.name, *command.aliases)}

    def _load(self) -> None:
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            logger.warning("Could not load custom commands: %s", type(error).__name__)
            return
        if not isinstance(payload, dict) or type(payload.get("version")) is not int or payload["version"] != SCHEMA_VERSION or not isinstance(payload.get("commands"), list):
            logger.warning("Ignoring unsupported or malformed custom command data")
            return
        commands: dict[str, CustomCommand] = {}
        used = set(self._built_in_names)
        for raw in payload["commands"]:
            try:
                command = parse_custom_command(raw)
                if command.id in commands or any(name in used for name in (command.name, *command.aliases)):
                    raise ValueError("Duplicate command ID, name, or alias")
            except ValueError as error:
                logger.warning("Ignoring invalid custom command: %s", error)
                continue
            commands[command.id] = command
            used.update((command.name, *command.aliases))
        self._publish(commands)

    def _write(self, commands: dict[str, CustomCommand]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self._path.parent,
                                             prefix=f".{self._path.name}.", suffix=".tmp", delete=False) as output:
                temporary_path = Path(output.name)
                json.dump({"version": SCHEMA_VERSION, "commands": [command.to_json() for command in commands.values()]}, output, indent=2)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            preserve_settings_recovery(
                self._path,
                {"version": SCHEMA_VERSION, "commands": [command.to_json() for command in self._commands.values()]},
                version=SCHEMA_VERSION,
            )
            temporary_path.replace(self._path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
