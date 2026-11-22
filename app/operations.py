"""One registry of panel operations shared by the Desktop bridge and the Server API.

A method becomes an operation with ``@operation``. Its argument model is built from
the signature (unknown fields are rejected); keyword-only parameters are private
host context (for example the browser session ``owner``) and never come from input.
"""

from __future__ import annotations

from app.errors import UserError, validation_error
import inspect
from dataclasses import dataclass
from functools import cache
from typing import Annotated, Any, Callable, Iterable, get_type_hints

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictFloat, ValidationError, create_model

DESKTOP = "desktop"
SERVER = "server"
BOTH = frozenset({DESKTOP, SERVER})
MAX_BODY = 64 * 1024


@dataclass(frozen=True)
class Operation:
    name: str
    attribute: str
    write: bool
    hosts: frozenset[str]
    max_body: int
    # Server returns a failed result's own fields only for these; others get a generic text.
    passthrough_errors: bool
    failure: str | None
    timeout: float
    timeout_failure: str | None
    validation_failure: str | None
    cancelled_failure: str | None
    arguments: type[BaseModel]

    def bind(self, payload: object) -> dict[str, Any]:
        """Validate a JSON object against the signature; raise ValueError on mismatch."""
        if not isinstance(payload, dict):
            raise UserError("operations.operation_arguments_must_be_a_json_object")
        try:
            parsed = self.arguments.model_validate(payload)
        except ValidationError as error:
            raise validation_error(error) from None
        return parsed.model_dump(mode="json", exclude_unset=True)


def operation(name: str | None = None, *, write: bool, hosts: Iterable[str] = BOTH,
              max_body: int = MAX_BODY, passthrough_errors: bool = False,
              failure: str | None = None, timeout: float = 10.0,
              timeout_failure: str | None = None, validation_failure: str | None = None,
              cancelled_failure: str | None = None) -> Callable:
    def decorate(function: Callable) -> Callable:
        function.__operation__ = {
            "name": name or function.__name__.lstrip("_"), "write": write, "hosts": frozenset(hosts),
            "max_body": max_body, "passthrough_errors": passthrough_errors,
            "failure": failure, "timeout": timeout, "timeout_failure": timeout_failure,
            "validation_failure": validation_failure, "cancelled_failure": cancelled_failure,
        }
        return function
    return decorate


@cache
def _payload_types() -> dict[tuple[str, str], Any]:
    from app.announcements import AnnouncementModel
    from app.custom_commands import CustomCommandModel
    from app.message_triggers import MessageTriggerInput
    from app.filter_settings import FilterSettingsModel
    from app.config.ai_setup import AISetupModel
    from app.command_restrictions import RestrictionModel
    from app.command_settings import CommandOverrideModel
    from app.fun_settings import FunResponse

    # Input IDs are assigned by the stores; disk models require them.
    custom_input = create_model("CustomCommandInput", __base__=CustomCommandModel,
                                id=(CustomCommandModel.model_fields["id"].annotation | None, None))
    announcement_input = create_model("AnnouncementInput", __base__=AnnouncementModel,
                                      id=(AnnouncementModel.model_fields["id"].annotation | None, None))
    restriction_input = create_model("RestrictionInput", __config__=ConfigDict(extra="forbid"),
        **{key: (RestrictionModel.model_fields[key].rebuild_annotation(), ...)
           for key in ("username", "command_ids", "expires_at", "note")},
        id=(RestrictionModel.model_fields["id"].rebuild_annotation() | None, None),
        scope=(RestrictionModel.model_fields["scope"].annotation, "channel"))
    command_options = create_model("CommandOptions", __config__=ConfigDict(extra="forbid"),
        **{key: (CommandOverrideModel.model_fields[key].rebuild_annotation(), None)
           for key in ("primary_name", "aliases", "display_name", "burst_interval_ms", "burst_max_count",
                       "send_as", "entry_limit", "chat_template", "stream_availability")},
        reactivate_removed=(StrictBool, False))
    # The management handlers are also called directly and still accept dictionaries.
    return {
        ("save_custom_command", "command"): custom_input,
        ("save_message_triggers", "triggers"): Annotated[list[MessageTriggerInput], Field(strict=True, max_length=100)],
        ("save_announcements", "announcements"): Annotated[list[announcement_input], Field(strict=True, max_length=50)],
        ("save_ai_setup", "settings"): AISetupModel,
        ("apply_filters", "payload"): FilterSettingsModel,
        ("save_filters", "payload"): FilterSettingsModel,
        ("save_command_restriction", "data"): restriction_input,
        ("apply_command_settings", "options"): command_options | None,
        ("save_command_settings", "options"): command_options | None,
        ("apply_command_responses", "responses"): Annotated[list[FunResponse], Field(strict=True, min_length=1, max_length=1000)],
        ("save_command_responses", "responses"): Annotated[list[FunResponse], Field(strict=True, min_length=1, max_length=1000)],
    }


def _arguments_model(name: str, function: Callable) -> type[BaseModel]:
    payload_types = _payload_types()
    annotations = get_type_hints(function, include_extras=True)
    fields: dict[str, Any] = {}
    for parameter in list(inspect.signature(function).parameters.values())[1:]:
        if parameter.kind is parameter.POSITIONAL_OR_KEYWORD:
            default = ... if parameter.default is parameter.empty else parameter.default
            annotation = payload_types.get((name, parameter.name), annotations.get(parameter.name, Any))
            if annotation in (bool, int, float):
                annotation = {bool: StrictBool, int: StrictInt, float: StrictFloat}[annotation]
            fields[parameter.name] = (annotation, default)
        elif parameter.kind in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD):
            raise TypeError(f"Operation {name} must use named parameters.")
    return create_model(f"{name}_arguments", __config__=ConfigDict(extra="forbid"), **fields)


def collect(*classes: type) -> dict[str, Operation]:
    """Build the registry; a later class overrides an operation of an earlier one."""
    registry: dict[str, Operation] = {}
    for cls in classes:
        seen: set[str] = set()
        for attribute, function in vars(cls).items():
            meta = getattr(function, "__operation__", None)
            if meta is None:
                continue
            if meta["name"] in seen:
                raise TypeError(f"Duplicate operation {meta['name']} in {cls.__name__}.")
            seen.add(meta["name"])
            arguments = _arguments_model(meta["name"], function)
            # These payloads expose catalog codes, including field constraints, on both hosts.
            if any(operation_name == meta["name"] for operation_name, _ in _payload_types()):
                meta = {**meta, "passthrough_errors": True}
            registry[meta["name"]] = Operation(attribute=attribute, arguments=arguments, **meta)
    return registry


def private_context(function: Callable, **context: object) -> dict[str, object]:
    """Keyword-only host context that a method declares, e.g. ``owner``."""
    parameters = inspect.signature(function).parameters
    return {key: value for key, value in context.items()
            if key in parameters and parameters[key].kind is inspect.Parameter.KEYWORD_ONLY}
