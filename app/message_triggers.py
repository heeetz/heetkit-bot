"""Validated local reactions to ordinary chat messages."""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path

from app.custom_commands import MAX_RESPONSE_LENGTH


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

    def matches(self, content: str) -> bool:
        haystack = content if self.case_sensitive else content.casefold()
        needle = self.text if self.case_sensitive else self.text.casefold()
        if self.match_mode == "exact":
            return haystack == needle
        return needle in haystack


def _number(value: object, name: str, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number.")
    if not 0 <= value <= maximum:
        raise ValueError(f"{name} must be between 0 and {maximum}.")
    if not math.isfinite(float(value)):
        raise ValueError(f"{name} must be a finite number.")
    return float(value)


def _response(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or "\n" in value or "\r" in value:
        raise ValueError("Responses must be non-empty single lines.")
    try:
        if len(value.encode("utf-8")) > MAX_RESPONSE_LENGTH:
            raise ValueError("Responses must be at most 450 UTF-8 bytes.")
    except UnicodeEncodeError as error:
        raise ValueError("Responses must contain valid Unicode.") from error
    return value.strip()


def parse_message_trigger(raw: object) -> MessageTrigger:
    if not isinstance(raw, dict):
        raise ValueError("Trigger must be an object.")
    identifier = raw.get("id")
    if not isinstance(identifier, str) or not identifier or len(identifier) > 40 or not all(
        character.isascii() and (character.isalnum() or character in "_-") for character in identifier
    ):
        raise ValueError("Trigger ID must use 1-40 ASCII letters, digits, _ or -.")
    if type(raw.get("enabled")) is not bool or type(raw.get("case_sensitive")) is not bool:
        raise ValueError("Enabled and case_sensitive must be booleans.")
    mode = raw.get("match_mode")
    if mode not in ("contains", "exact"):
        raise ValueError("Match mode must be contains or exact.")
    text = raw.get("text")
    if not isinstance(text, str) or not text.strip() or len(text) > 100 or "\n" in text or "\r" in text:
        raise ValueError("Match text must be one non-empty line of at most 100 characters.")
    responses = raw.get("responses")
    if not isinstance(responses, list) or not 1 <= len(responses) <= 10:
        raise ValueError("Provide 1-10 responses.")
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
    )


class MessageTriggerStore:
    """Load a bounded, immutable set of reactions once at application composition."""

    def __init__(self, path: Path) -> None:
        self._triggers: tuple[MessageTrigger, ...] = ()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            logger.warning("Could not load message triggers: %s", type(error).__name__)
            return
        if not isinstance(payload, dict) or type(payload.get("version")) is not int or payload["version"] != SCHEMA_VERSION or not isinstance(payload.get("triggers"), list):
            logger.warning("Ignoring unsupported or malformed message trigger data")
            return
        loaded: list[MessageTrigger] = []
        used: set[str] = set()
        for raw in payload["triggers"][:100]:
            try:
                trigger = parse_message_trigger(raw)
                if trigger.id in used:
                    raise ValueError("Duplicate trigger ID")
            except ValueError as error:
                logger.warning("Ignoring invalid message trigger: %s", error)
                continue
            loaded.append(trigger)
            used.add(trigger.id)
        if len(payload["triggers"]) > 100:
            logger.warning("Ignoring message triggers after the first 100 entries")
        self._triggers = tuple(loaded)

    def list(self) -> tuple[MessageTrigger, ...]:
        return self._triggers
