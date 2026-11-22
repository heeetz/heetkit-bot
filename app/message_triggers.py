"""Validated local reactions to ordinary chat messages."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
from pathlib import Path
from threading import RLock

from app.errors import UserError
from app.command_order import CommandCreationOrder
from typing import Annotated, Literal
from pydantic import AfterValidator, ConfigDict, Field, StrictBool, StrictStr
from app.settings_models import (SettingsModel, Identifier, ChatLine, CooldownSeconds, single_line, field_value,
    CreationOrder, parse)
from app.settings_recovery import preserve_settings_recovery


logger = logging.getLogger(__name__)
SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class MessageTrigger:
    id: str
    enabled: bool
    match_mode: str
    text: str
    case_sensitive: bool
    probability: float
    cooldown_seconds: float
    responses: tuple[str, ...]
    creation_order: int = 0

    def to_json(self, *, include_order: bool = True) -> dict[str, object]:
        result = asdict(self)
        result["responses"] = list(self.responses)
        if not include_order or not self.creation_order:
            result.pop("creation_order")
        return result

    def matches(self, content: str) -> bool:
        haystack = content if self.case_sensitive else content.casefold()
        needle = self.text if self.case_sensitive else self.text.casefold()
        if self.match_mode == "exact":
            return haystack == needle
        return needle in haystack


class MessageTriggerModel(SettingsModel):
    id: Identifier
    enabled: StrictBool
    match_mode: Literal["contains", "exact"]
    text: Annotated[StrictStr, Field(max_length=100), AfterValidator(single_line)]
    case_sensitive: StrictBool
    probability: Annotated[CooldownSeconds, Field(le=1)]
    cooldown_seconds: CooldownSeconds
    responses: Annotated[list[ChatLine], Field(strict=True, min_length=1, max_length=10)]
    creation_order: CreationOrder = 0


_TRIGGER_FIELDS = frozenset(MessageTriggerModel.model_fields)


class MessageTriggerInput(MessageTriggerModel):
    model_config = ConfigDict(extra="forbid")


def parse_message_trigger(raw: object) -> MessageTrigger:
    item = parse(MessageTriggerModel, raw)
    return MessageTrigger(**{**item.model_dump(), "responses": tuple(item.responses)})


def trigger_revision(triggers: tuple[MessageTrigger, ...]) -> str:
    data = json.dumps([asdict(trigger) for trigger in triggers], sort_keys=True)
    return sha256(data.encode("ascii")).hexdigest()


class MessageTriggerStore:
    """Keep immutable trigger snapshots behind one lock; publish after atomic save."""

    def __init__(self, path: Path, *, creation_order: CommandCreationOrder | None = None) -> None:
        self._path = path
        self._lock = RLock()
        self._creation_order = creation_order or CommandCreationOrder()
        self._triggers: tuple[MessageTrigger, ...] = ()
        try:
            # ``utf-8-sig`` accepts both ordinary UTF-8 and the BOM emitted by
            # some Windows editors while still rejecting other encodings.
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except FileNotFoundError:
            return
        except json.JSONDecodeError as error:
            logger.warning(
                "Could not load message triggers path=%s error=%s line=%d column=%d position=%d; reactions disabled",
                path,
                type(error).__name__,
                error.lineno,
                error.colno,
                error.pos,
            )
            return
        except UnicodeError as error:
            logger.warning(
                "Could not load message triggers path=%s error=%s position=%s; reactions disabled",
                path,
                type(error).__name__,
                getattr(error, "start", "unknown"),
            )
            return
        except OSError as error:
            logger.warning(
                "Could not load message triggers path=%s error=%s; reactions disabled",
                path,
                type(error).__name__,
            )
            return
        if not isinstance(payload, dict) or type(payload.get("version")) is not int or payload["version"] != SCHEMA_VERSION or not isinstance(payload.get("triggers"), list):
            logger.warning(
                "Ignoring unsupported or malformed message trigger data path=%s; reactions disabled",
                path,
            )
            return
        loaded: list[MessageTrigger] = []
        used: set[str] = set()
        for raw in payload["triggers"][:100]:
            try:
                trigger = parse_message_trigger(raw)
                if trigger.id in used:
                    raise UserError("message_triggers.duplicate_trigger_id")
            except ValueError as error:
                logger.warning("Ignoring invalid message trigger path=%s: %s", path, error)
                continue
            loaded.append(trigger)
            used.add(trigger.id)
        if len(payload["triggers"]) > 100:
            logger.warning("Ignoring message triggers after the first 100 entries")
        self._triggers = tuple(loaded)
        self._creation_order.observe(max((trigger.creation_order for trigger in loaded), default=0))

    def list(self) -> tuple[MessageTrigger, ...]:
        with self._lock:
            return self._triggers

    def save(self, payload: object, *, revision: str | None = None) -> tuple[MessageTrigger, ...]:
        """Validate and atomically persist a complete trigger collection."""
        payload = field_value(Annotated[list, Field(strict=True, max_length=100)], payload, "triggers")

        with self._lock:
            if revision is not None and revision != trigger_revision(self._triggers):
                raise UserError("message_triggers.chat_reactions_changed_reload_them_before")
            parsed: list[MessageTrigger] = []
            used: set[str] = set()
            previous_order = {trigger.id: trigger.creation_order for trigger in self._triggers}
            for raw in payload:
                if isinstance(raw, dict):
                    raw = {**raw, "creation_order": 0}
                item = parse(MessageTriggerInput, raw)
                trigger = MessageTrigger(**{**item.model_dump(), "responses": tuple(item.responses)})
                if trigger.id in used:
                    raise UserError("message_triggers.duplicate_trigger_id")
                order = previous_order[trigger.id] if trigger.id in previous_order else self._creation_order.next()
                parsed.append(replace(trigger, creation_order=order))
                used.add(trigger.id)

            updated = tuple(parsed)
            self._write(updated)
            self._triggers = updated
            return updated

    def _write(self, triggers: tuple[MessageTrigger, ...]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self._path.parent,
                prefix=f".{self._path.name}.",
                suffix=".tmp",
                delete=False,
            ) as output:
                temporary_path = Path(output.name)
                json.dump(
                    {
                        "version": SCHEMA_VERSION,
                        "triggers": [trigger.to_json() for trigger in triggers],
                    },
                    output,
                    indent=2,
                    ensure_ascii=False,
                )
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            preserve_settings_recovery(
                self._path,
                {
                    "version": SCHEMA_VERSION,
                    "triggers": [trigger.to_json() for trigger in self._triggers],
                },
                version=SCHEMA_VERSION,
                encoding="utf-8-sig",
            )
            os.replace(temporary_path, self._path)
            temporary_path = None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
