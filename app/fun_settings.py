"""Profile-owned responses for existing fun commands."""

from __future__ import annotations

import logging
from threading import RLock

from app.errors import UserError
from typing import Annotated
from pydantic import Field, StrictStr
from app.settings_models import SettingsModel, byte_limit, field_value, parse
from app.config_file import ConfigFile

FATES = ("Tomorrow brings a new opportunity.",)


def validate_fates(values: object) -> tuple[str, ...]:
    return _validate_responses(values, max_responses=1000)


FunResponse = Annotated[StrictStr, Field(pattern=r"\S"), byte_limit(450)]


class FunSettingsModel(SettingsModel):
    fates: Annotated[list[FunResponse], Field(strict=True, min_length=1, max_length=1000)] = list(FATES)


def _validate_responses(values: object, *, max_responses: int) -> tuple[str, ...]:
    return tuple(field_value(Annotated[list[FunResponse], Field(strict=True, min_length=1, max_length=max_responses)],
                             values, "responses"))


def _response_options(command_name: str) -> tuple[str, tuple[str, ...], int]:
    if command_name == "fate":
        return "fates", FATES, 1000
    raise UserError("fun_settings.command_has_no_editable_responses")


class FunSettingsStore:
    """One versioned store, preserving existing owner responses and other fields."""

    def __init__(self, config: ConfigFile) -> None:
        self.section = config.section("fun")
        self._lock = RLock()
        self._payload: dict[str, object] = {"version": 1}
        self._load_error = False
        self._fates = FATES
        try:
            payload = self.section.load()
            if (not isinstance(payload, dict) or type(payload.get("version")) is not int
                    or payload["version"] != 1):
                raise UserError("fun_settings.unsupported_fun_settings")
            self._payload = payload
        except FileNotFoundError:
            pass
        except (OSError, UnicodeError, ValueError):
            self._load_error = True
            logging.getLogger(__name__).warning("Could not load local fun settings; using neutral defaults")
        try:
            self._fates = tuple(parse(FunSettingsModel, {"fates": self._payload.get("fates", list(FATES))}).fates)
        except ValueError:
            logging.getLogger(__name__).warning("Invalid local fate responses; using neutral defaults")
        self._saved_fates = self._fates

    @property
    def fates(self) -> tuple[str, ...]:
        with self._lock:
            return self._fates

    def snapshot(self, command_name: str = "fate") -> dict[str, object]:
        field, defaults, max_responses = _response_options(command_name)
        with self._lock:
            responses = self._fates
            saved_responses = self._saved_fates
            return {
                "responses": list(responses), "defaults": list(defaults),
                "saved": responses == saved_responses,
                "has_saved_override": field in self._payload,
                "response_mode": "random",
                "max_responses": max_responses,
            }

    def apply(self, responses: object, command_name: str = "fate") -> None:
        _, _, max_responses = _response_options(command_name)
        parsed = _validate_responses(responses, max_responses=max_responses)
        with self._lock:
            self._set_responses(command_name, parsed, saved=False)

    def save(self, responses: object, command_name: str = "fate") -> None:
        field, _, max_responses = _response_options(command_name)
        parsed = _validate_responses(responses, max_responses=max_responses)
        with self._lock:
            payload = {**self._payload, field: list(parsed)}
            self._write(payload)
            self._payload = payload
            self._set_responses(command_name, parsed, saved=True)

    def reset(self, command_name: str = "fate") -> None:
        field, defaults, _ = _response_options(command_name)
        with self._lock:
            payload = dict(self._payload)
            payload.pop(field, None)
            self._write(payload)
            self._payload = payload
            self._set_responses(command_name, defaults, saved=True)

    def _set_responses(self, command_name: str, responses: tuple[str, ...], *, saved: bool) -> None:
        self._fates = responses
        if saved:
            self._saved_fates = responses

    def reset_all(self) -> None:
        """Restore the factory response pool in one atomic profile write."""
        with self._lock:
            payload = {key: value for key, value in self._payload.items() if key != "fates"}
            self._write(payload)
            self._payload = payload
            self._set_responses("fate", FATES, saved=True)

    def _write(self, payload: dict[str, object]) -> None:
        if self._load_error:
            raise UserError("fun_settings.repair_unreadable_unsupported_fun_settings_json")
        self.section.save(payload, recovered=self._payload, version=1)
