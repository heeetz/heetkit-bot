"""One registry of panel operations shared by the Desktop bridge and the Server API.

A method becomes an operation with ``@operation``. Its argument model is built from
the signature (unknown fields are rejected); keyword-only parameters are private
host context (for example the browser session ``owner``) and never come from input.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from pydantic import BaseModel, ConfigDict, ValidationError, create_model

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
    arguments: type[BaseModel]

    def bind(self, payload: object) -> dict[str, Any]:
        """Validate a JSON object against the signature; raise ValueError on mismatch."""
        if not isinstance(payload, dict):
            raise ValueError("Operation arguments must be a JSON object.")
        try:
            parsed = self.arguments.model_validate(payload)
        except ValidationError:
            raise ValueError("Invalid operation arguments.") from None
        return parsed.model_dump(exclude_unset=True)


def operation(name: str | None = None, *, write: bool, hosts: Iterable[str] = BOTH,
              max_body: int = MAX_BODY, passthrough_errors: bool = False) -> Callable:
    def decorate(function: Callable) -> Callable:
        function.__operation__ = {
            "name": name or function.__name__.lstrip("_"), "write": write, "hosts": frozenset(hosts),
            "max_body": max_body, "passthrough_errors": passthrough_errors,
        }
        return function
    return decorate


def _arguments_model(name: str, function: Callable) -> type[BaseModel]:
    fields: dict[str, Any] = {}
    for parameter in list(inspect.signature(function).parameters.values())[1:]:
        if parameter.kind is parameter.POSITIONAL_OR_KEYWORD:
            default = ... if parameter.default is parameter.empty else parameter.default
            fields[parameter.name] = (Any, default)
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
            registry[meta["name"]] = Operation(attribute=attribute, arguments=_arguments_model(meta["name"], function), **meta)
    return registry


def private_context(function: Callable, **context: object) -> dict[str, object]:
    """Keyword-only host context that a method declares, e.g. ``owner``."""
    parameters = inspect.signature(function).parameters
    return {key: value for key, value in context.items()
            if key in parameters and parameters[key].kind is inspect.Parameter.KEYWORD_ONLY}
