"""Profile-owned responses for existing fun commands."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from threading import RLock

from app.config.commands import TG_MESSAGE
from app.settings_recovery import migrate_settings_key, preserve_settings_recovery

FATES = ("Tomorrow brings a new opportunity.",)


def validate_fates(values: object) -> tuple[str, ...]:
    return _validate_responses(values, max_responses=1000)


def _validate_responses(values: object, *, max_responses: int) -> tuple[str, ...]:
    if not isinstance(values, list) or not 1 <= len(values) <= max_responses:
        raise ValueError(f"Provide between 1 and {max_responses} command responses.")
    if any(not isinstance(value, str) or not value.strip() or len(value.encode("utf-8")) > 450
           for value in values):
        raise ValueError("Each response must contain text and be at most 450 UTF-8 bytes.")
    return tuple(values)


def _response_options(command_name: str) -> tuple[str, tuple[str, ...], int]:
    if command_name == "fate":
        return "fates", FATES, 1000
    if command_name == "tg":
        return "tg_message", (TG_MESSAGE,), 1
    raise ValueError("This command has no editable responses.")


class FunSettingsStore:
    """One versioned store, preserving existing owner responses and other fields."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = RLock()
        self._payload: dict[str, object] = {"version": 1}
        self._load_error = False
        self.tg_message = TG_MESSAGE
        self._fates = FATES
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if (not isinstance(payload, dict) or type(payload.get("version")) is not int
                        or payload["version"] != 1):
                    raise ValueError("Unsupported fun settings")
                self._payload = migrate_settings_key(path, payload, "forecasts", "fates", version=1)
            except (OSError, UnicodeError, ValueError):
                self._load_error = True
                logging.getLogger(__name__).warning("Could not load local fun settings; using neutral defaults")
        message = self._payload.get("tg_message", TG_MESSAGE)
        if isinstance(message, str) and message.strip() and len(message.encode("utf-8")) <= 450:
            self.tg_message = message
        try:
            self._fates = validate_fates(self._payload.get("fates", list(FATES)))
        except ValueError:
            logging.getLogger(__name__).warning("Invalid local fate responses; using neutral defaults")
        self._saved_fates = self._fates
        self._saved_tg_message = self.tg_message

    @property
    def fates(self) -> tuple[str, ...]:
        with self._lock:
            return self._fates

    def snapshot(self, command_name: str = "fate") -> dict[str, object]:
        field, defaults, max_responses = _response_options(command_name)
        with self._lock:
            responses = (self.tg_message,) if command_name == "tg" else self._fates
            saved_responses = (self._saved_tg_message,) if command_name == "tg" else self._saved_fates
            return {
                "responses": list(responses), "defaults": list(defaults),
                "saved": responses == saved_responses,
                "has_saved_override": field in self._payload,
                "response_mode": "single" if command_name == "tg" else "random",
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
            payload = {**self._payload, field: parsed[0] if command_name == "tg" else list(parsed)}
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
        if command_name == "tg":
            self.tg_message = responses[0]
            if saved:
                self._saved_tg_message = responses[0]
        else:
            self._fates = responses
            if saved:
                self._saved_fates = responses

    def _write(self, payload: dict[str, object]) -> None:
        if self._load_error:
            raise ValueError("Repair the unreadable or unsupported fun_settings.json before saving responses.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent, delete=False) as output:
                temporary = Path(output.name)
                json.dump(payload, output, ensure_ascii=False, indent=2)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            preserve_settings_recovery(self.path, self._payload, version=1)
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
