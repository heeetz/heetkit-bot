"""Profile-owned responses for existing fun commands."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from threading import RLock

from config import TG_MESSAGE

FORECASTS = ("Tomorrow brings a new opportunity.",)


def validate_forecasts(values: object) -> tuple[str, ...]:
    if not isinstance(values, list) or not 1 <= len(values) <= 1000:
        raise ValueError("Provide between 1 and 1000 forecast responses.")
    if any(not isinstance(value, str) or not value.strip() or len(value.encode("utf-8")) > 450
           for value in values):
        raise ValueError("Each response must contain text and be at most 450 UTF-8 bytes.")
    return tuple(values)


class FunSettingsStore:
    """One versioned store, preserving existing owner responses and other fields."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = RLock()
        self._payload: dict[str, object] = {"version": 1}
        self._load_error = False
        self.tg_message = TG_MESSAGE
        self._forecasts = FORECASTS
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(payload, dict) or payload.get("version") != 1:
                    raise ValueError("Unsupported fun settings")
                self._payload = payload
            except (OSError, UnicodeError, ValueError):
                self._load_error = True
                logging.getLogger(__name__).warning("Could not load local fun settings; using neutral defaults")
        message = self._payload.get("tg_message", TG_MESSAGE)
        if isinstance(message, str) and message.strip() and len(message.encode("utf-8")) <= 450:
            self.tg_message = message
        try:
            self._forecasts = validate_forecasts(self._payload.get("forecasts", list(FORECASTS)))
        except ValueError:
            logging.getLogger(__name__).warning("Invalid local forecast responses; using neutral defaults")
        self._saved_forecasts = self._forecasts

    @property
    def forecasts(self) -> tuple[str, ...]:
        with self._lock:
            return self._forecasts

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "responses": list(self._forecasts), "defaults": list(FORECASTS),
                "saved": self._forecasts == self._saved_forecasts,
                "has_saved_override": "forecasts" in self._payload,
            }

    def apply(self, responses: object) -> None:
        parsed = validate_forecasts(responses)
        with self._lock:
            self._forecasts = parsed

    def save(self, responses: object) -> None:
        parsed = validate_forecasts(responses)
        with self._lock:
            payload = {**self._payload, "forecasts": list(parsed)}
            self._write(payload)
            self._payload = payload
            self._forecasts = self._saved_forecasts = parsed

    def reset(self) -> None:
        with self._lock:
            payload = dict(self._payload)
            payload.pop("forecasts", None)
            self._write(payload)
            self._payload = payload
            self._forecasts = self._saved_forecasts = FORECASTS

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
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
