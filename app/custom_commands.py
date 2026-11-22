"""Validated, non-executable local custom commands."""

from __future__ import annotations

import json
import logging
import os
import random
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from threading import RLock
from uuid import UUID, uuid4
from typing import Annotated, Literal
from pydantic import AfterValidator, Field, StrictBool, StrictInt, StrictStr, model_validator

from app.settings_models import (SettingsModel, CommandName, CooldownSeconds, BurstInterval,
    CreationOrder, PermissionName, StreamAvailability, SendAs, single_line, parse)

from app.errors import UserError
from app.twitch.permissions import Permission
from app.command_order import CommandCreationOrder
from app.settings_recovery import preserve_settings_recovery
from app.utils.cooldown import CooldownPolicy
from app.utils.text import CHAT_RESPONSE_BYTES, normalize_command_name, render_chat_template


logger = logging.getLogger(__name__)
SCHEMA_VERSION = 2
MAX_RESPONSE_LENGTH = CHAT_RESPONSE_BYTES
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
    response_mode: str
    burst_count: int = 1
    burst_allow_override: bool = False
    burst_interval_ms: int = 0
    stream_availability: str = "anytime"
    send_as: str = "chat"
    creation_order: int = 0

    def to_json(self, *, include_order: bool = True) -> dict[str, object]:
        result: dict[str, object] = {
            "id": self.id,
            "name": self.name,
            "enabled": self.enabled,
            "responses": list(self.responses),
            "permission": self.permission.name,
            "per_user_seconds": self.cooldown.per_user_seconds,
            "global_seconds": self.cooldown.global_seconds,
            "aliases": list(self.aliases),
            "response_mode": self.response_mode,
        }
        if self.response_mode == "burst":
            result.update(burst_count=self.burst_count, burst_allow_override=self.burst_allow_override)
            if self.burst_interval_ms:
                result["burst_interval_ms"] = self.burst_interval_ms
        if self.stream_availability != "anytime":
            result["stream_availability"] = self.stream_availability
        if self.send_as != "chat":
            result["send_as"] = self.send_as
        if include_order and self.creation_order:
            result["creation_order"] = self.creation_order
        return result


def _response(value: object) -> str:
    variables = _VARIABLE_PATTERN.findall(value)
    if any(variable not in VARIABLES for variable in variables):
        raise UserError("custom_commands.response_contains_unknown_variable")
    if "{" in _VARIABLE_PATTERN.sub("", value) or "}" in _VARIABLE_PATTERN.sub("", value):
        raise UserError("custom_commands.response_has_invalid_variable_placeholder")
    return value.strip()


class CustomCommandModel(SettingsModel):
    id: UUID
    name: CommandName
    enabled: StrictBool
    responses: Annotated[list[Annotated[StrictStr, Field(max_length=2000), AfterValidator(single_line)]], Field(strict=True, min_length=1, max_length=30)]
    permission: PermissionName
    per_user_seconds: CooldownSeconds
    global_seconds: CooldownSeconds
    aliases: Annotated[list[CommandName], Field(strict=True, max_length=10)]
    response_mode: Literal["single", "random", "burst"] | None = None
    burst_count: Annotated[StrictInt, Field(ge=1, le=10)] = 1
    burst_allow_override: StrictBool = False
    burst_interval_ms: BurstInterval = 0
    stream_availability: StreamAvailability = "anytime"
    send_as: SendAs = "chat"
    creation_order: CreationOrder = 0

    @model_validator(mode="after")
    def command_rules(self):
        if self.response_mode is None:
            if "response_mode" in self.model_fields_set:
                raise UserError("validation.choice", field="response_mode", options="single, random, burst")
            self.response_mode = "random" if len(self.responses) > 1 else "single"
        self.responses = [_response(value) for value in self.responses]
        if self.response_mode != "random" and len(self.responses) != 1:
            raise UserError("custom_commands.single_burst_modes_require_exactly_one")
        if self.response_mode == "burst":
            if Permission[self.permission] < Permission.MODERATOR:
                raise UserError("custom_commands.burst_mode_requires_moderator_broadcaster_permission")
        elif self.model_fields_set & {"burst_count", "burst_allow_override", "burst_interval_ms"}:
            raise UserError("custom_commands.burst_settings_require_burst_response_mode")
        if len({self.name, *self.aliases}) != 1 + len(self.aliases):
            raise UserError("custom_commands.command_name_aliases_unique")
        return self


def parse_custom_command(raw: object, *, command_id: str | None = None) -> CustomCommand:
    if command_id is not None and isinstance(raw, dict):
        raw = {**raw, "id": command_id}
    item = parse(CustomCommandModel, raw)
    values = item.model_dump(exclude={"per_user_seconds", "global_seconds", "permission", "id"})
    return CustomCommand(**{**values, "responses": tuple(item.responses), "aliases": tuple(item.aliases)},
        id=str(item.id), permission=Permission[item.permission],
        cooldown=CooldownPolicy(item.per_user_seconds, item.global_seconds))


def render_response(command: CustomCommand, arguments: str, sender: str, random_user: str,
                    *, template: str | None = None) -> str:
    parts = arguments.split()
    values = {"sender": sender, "target": (parts[0].lstrip("@") or sender) if parts else sender,
              "args": arguments, "random_user": random_user}
    values.update({f"arg{i}": parts[i - 1] if i <= len(parts) else "" for i in range(1, MAX_POSITIONAL_ARGUMENTS + 1)})
    template = template if template is not None else random.choice(command.responses)
    expanded = render_chat_template(template, values)
    return expanded.encode("utf-8")[:MAX_RESPONSE_LENGTH].decode("utf-8", errors="ignore").strip()


class CustomCommandStore:
    """Keep immutable command snapshots behind one lock; publish after atomic save."""

    def __init__(self, path: Path, built_in_names: set[str], *, namespace_lock=None,
                 creation_order: CommandCreationOrder | None = None) -> None:
        self._path = path
        self._built_in_names = built_in_names | {"optout"}
        self._builtin_names_provider: Callable[[], set[str]] | None = None
        self._lock = namespace_lock if namespace_lock is not None else RLock()
        self._commands: dict[str, CustomCommand] = {}
        self._lookup: dict[str, str] = {}
        self._creation_order = creation_order or CommandCreationOrder()
        self._load()

    def list(self) -> tuple[CustomCommand, ...]:
        with self._lock:
            return tuple(sorted(self._commands.values(), key=lambda command: command.name))

    def get_by_name(self, name: str) -> CustomCommand | None:
        with self._lock:
            return self._commands.get(self._lookup.get(normalize_command_name(name), ""))

    def save(self, raw: object) -> CustomCommand:
        if not isinstance(raw, dict):
            raise UserError("custom_commands.custom_command_must_be_an_object")
        with self._lock:
            requested_id = raw.get("id")
            if requested_id is not None and requested_id not in self._commands:
                raise UserError("custom_commands.unknown_custom_command_id")
            if requested_id is not None:
                current = self._commands[requested_id]
                raw = {"stream_availability": current.stream_availability, "send_as": current.send_as, **raw}
            command = parse_custom_command({**raw, "creation_order": 0}, command_id=requested_id or str(uuid4()))
            order = self._commands[requested_id].creation_order if requested_id is not None else self._creation_order.next()
            command = replace(command, creation_order=order)
            updated = dict(self._commands)
            updated[command.id] = command
            self._validate_collisions(updated)
            self._write(updated)
            self._publish(updated)
            return command

    def delete(self, identifier: str) -> None:
        with self._lock:
            if identifier not in self._commands:
                raise UserError("custom_commands.unknown_custom_command_id")
            updated = dict(self._commands)
            del updated[identifier]
            self._write(updated)
            self._publish(updated)

    def _validate_collisions(self, commands: dict[str, CustomCommand]) -> None:
        used = set(self._built_in_names) if self._builtin_names_provider is None else self._builtin_names_provider()
        for command in commands.values():
            for name in (command.name, *command.aliases):
                if name in used:
                    raise UserError("custom_commands.command_name_alias_already_exists", name=str(name))
                used.add(name)

    def bind_builtin_names(self, provider: Callable[[], set[str]]) -> None:
        with self._lock:
            self._builtin_names_provider = provider

    def _publish(self, commands: dict[str, CustomCommand]) -> None:
        self._creation_order.observe(max((command.creation_order for command in commands.values()), default=0))
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
                    raise UserError("custom_commands.duplicate_command_id_name_or_alias")
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
