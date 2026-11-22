"""Validated local reactions to ordinary chat messages."""

from __future__ import annotations

import json
import logging
import math
import os
import tempfile
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
from pathlib import Path
from threading import RLock

from app.errors import UserError
from app.command_order import CommandCreationOrder, parse_creation_order
from app.custom_commands import MAX_RESPONSE_LENGTH
from app.settings_recovery import preserve_settings_recovery


logger = logging.getLogger(__name__)
SCHEMA_VERSION = 1
_TRIGGER_FIELDS = frozenset(
    {
        "id",
        "enabled",
        "match_mode",
        "text",
        "case_sensitive",
        "probability",
        "cooldown_seconds",
        "responses",
        "creation_order",
    }
)


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


def _number(value: object, name: str, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise UserError("message_triggers.must_be_a_finite_number", name=str(name))
    if not 0 <= value <= maximum:
        raise UserError("message_triggers.between_0", name=str(name), maximum=str(maximum))
    if not math.isfinite(float(value)):
        raise UserError("message_triggers.must_be_a_finite_number", name=str(name))
    return float(value)


def _response(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or "\n" in value or "\r" in value:
        raise UserError("message_triggers.responses_non_empty_single_lines")
    try:
        if len(value.encode("utf-8")) > MAX_RESPONSE_LENGTH:
            raise UserError("message_triggers.responses_most_450_utf_8_bytes")
    except UnicodeEncodeError as error:
        raise UserError("message_triggers.responses_contain_valid_unicode") from error
    return value.strip()


def parse_message_trigger(raw: object) -> MessageTrigger:
    if not isinstance(raw, dict):
        raise UserError("message_triggers.trigger_must_be_an_object")
    identifier = raw.get("id")
    if not isinstance(identifier, str) or not identifier or len(identifier) > 40 or not all(
        character.isascii() and (character.isalnum() or character in "_-") for character in identifier
    ):
        raise UserError("message_triggers.trigger_id_use_1_40_ascii")
    if type(raw.get("enabled")) is not bool or type(raw.get("case_sensitive")) is not bool:
        raise UserError("message_triggers.enabled_and_case_sensitive_must_be_booleans")
    mode = raw.get("match_mode")
    if mode not in ("contains", "exact"):
        raise UserError("message_triggers.match_mode_contains_exact")
    text = raw.get("text")
    if not isinstance(text, str) or not text.strip() or len(text) > 100 or "\n" in text or "\r" in text:
        raise UserError("message_triggers.match_text_one_non_empty_line")
    responses = raw.get("responses")
    if not isinstance(responses, list) or not 1 <= len(responses) <= 10:
        raise UserError("message_triggers.provide_1_10_responses")
    parsed_responses = tuple(_response(response) for response in responses)
    return MessageTrigger(
        id=identifier,
        enabled=raw["enabled"],
        match_mode=mode,
        text=text.strip(),
        case_sensitive=raw["case_sensitive"],
        probability=_number(raw.get("probability"), "Probability", 1),
        cooldown_seconds=_number(raw.get("cooldown_seconds"), "Cooldown", 86400),
        responses=parsed_responses,
        creation_order=parse_creation_order(raw.get("creation_order", 0)),
    )


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
        if not isinstance(payload, list):
            raise UserError("message_triggers.message_triggers_must_be_a_list")
        if len(payload) > 100:
            raise UserError("message_triggers.provide_most_100_message_triggers")

        with self._lock:
            if revision is not None and revision != trigger_revision(self._triggers):
                raise UserError("message_triggers.chat_reactions_changed_reload_them_before")
            parsed: list[MessageTrigger] = []
            used: set[str] = set()
            previous_order = {trigger.id: trigger.creation_order for trigger in self._triggers}
            for raw in payload:
                if not isinstance(raw, dict):
                    raise UserError("message_triggers.trigger_must_be_an_object")
                unknown = set(raw) - _TRIGGER_FIELDS
                if unknown:
                    raise UserError("message_triggers.unknown_trigger_field")
                trigger = parse_message_trigger({**raw, "creation_order": 0})
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
