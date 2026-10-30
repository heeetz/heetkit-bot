"""Installation-local access policy; never part of portable command configuration."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from uuid import uuid4

from app.ai_user_blocks import normalize_ai_username, verified_user_id
from app.settings_recovery import preserve_settings_recovery

MAX_RULES = 1000
MAX_DURATION = timedelta(days=366)
MAX_FILE_BYTES = 1024 * 1024


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def expiry(value: object) -> datetime | None:
    if value is None:
        return None
    try:
        if not isinstance(value, str) or len(value) > 40:
            raise ValueError
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError
        return result.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise ValueError("Expiry must be an absolute date with a UTC offset.") from None


@dataclass(frozen=True, slots=True)
class CommandRestriction:
    id: str
    channel_id: str
    twitch_user_id: str
    username: str
    command_ids: tuple[str, ...]
    expires_at: str | None
    note: str

    def active(self, now: datetime) -> bool:
        end = expiry(self.expires_at)
        return end is None or now < end


def parse_restriction(raw: object) -> CommandRestriction:
    fields = {"id", "channel_id", "twitch_user_id", "username", "command_ids", "expires_at", "note"}
    if not isinstance(raw, dict) or set(raw) != fields:
        raise ValueError("Unexpected or missing restriction fields.")
    if not isinstance(raw["id"], str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,40}", raw["id"]):
        raise ValueError("Invalid restriction ID.")
    if any(verified_user_id(raw[key]) is None for key in ("channel_id", "twitch_user_id")):
        raise ValueError("Restrictions require verified numeric user and channel IDs.")
    ids = raw["command_ids"]
    if (not isinstance(ids, (list, tuple)) or len(ids) > 200
            or any(not isinstance(key, str) or not re.fullmatch(r"(?:custom:)?[a-zA-Z0-9_-]{1,64}", key)
                   or key == "optout" for key in ids) or len(set(ids)) != len(ids)):
        raise ValueError("Select valid, distinct command IDs. The optout command cannot be restricted.")
    note = raw["note"]
    if not isinstance(note, str) or len(note) > 200 or any(ord(char) < 32 or ord(char) == 127 for char in note):
        raise ValueError("Private notes must be one line of at most 200 characters.")
    try:
        note.encode("utf-8")
    except UnicodeError:
        raise ValueError("Private notes must contain valid Unicode.") from None
    end = expiry(raw["expires_at"])
    return CommandRestriction(raw["id"], raw["channel_id"], raw["twitch_user_id"],
        normalize_ai_username(raw["username"]), tuple(ids), end.isoformat() if end else None, note)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate restriction key.")
        result[key] = value
    return result


class CommandRestrictionStore:
    """Publish only after durable replacement; invalid policy fails startup closed.

    Expiry is checked at dispatch, independent of cleanup. Startup and management
    reads/mutations physically remove expired rules, including their private notes.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = RLock()
        self._rules: tuple[CommandRestriction, ...] = ()
        try:
            with path.open("rb") as source:
                raw = source.read(MAX_FILE_BYTES + 1)
            if len(raw) > MAX_FILE_BYTES:
                raise ValueError
            payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
            if (not isinstance(payload, dict) or set(payload) != {"version", "restrictions"}
                    or type(payload["version"]) is not int or payload["version"] != 1
                    or not isinstance(payload["restrictions"], list) or len(payload["restrictions"]) > MAX_RULES):
                raise ValueError
            rules = tuple(parse_restriction(row) for row in payload["restrictions"])
            if len({rule.id for rule in rules}) != len(rules):
                raise ValueError
            self._rules = rules
        except FileNotFoundError:
            return
        except (ValueError, UnicodeError, RecursionError):
            raise ValueError("Invalid command_restrictions.json. Back up and repair the private policy file before starting.") from None
        self.list()

    def list(self) -> tuple[CommandRestriction, ...]:
        with self._lock:
            active = tuple(rule for rule in self._rules if rule.active(utcnow()))
            if active != self._rules:
                self._save(active)
            return active

    def match(self, channel_id: str, user_id: str, command_id: str) -> CommandRestriction | None:
        with self._lock:
            now = utcnow()
            matches = [rule for rule in self._rules if rule.channel_id == channel_id
                and rule.twitch_user_id == user_id and (not rule.command_ids or command_id in rule.command_ids)
                and rule.active(now)]
            # Report the widest remaining lifetime, including overlapping rules.
            return max(matches, key=lambda rule: expiry(rule.expires_at) or datetime.max.replace(tzinfo=timezone.utc), default=None)

    def get(self, identifier: object) -> CommandRestriction:
        with self._lock:
            for rule in self._rules:
                if rule.id == identifier and rule.active(utcnow()):
                    return rule
        raise ValueError("Restriction no longer exists or has expired. Refresh the list.")

    def save(self, data: dict, *, channel_id: str, user_id: str, valid_command_ids: set[str]) -> None:
        with self._lock:
            old = self.get(data["id"]) if "id" in data else None
            rule = parse_restriction({**data, "id": old.id if old else uuid4().hex,
                "channel_id": old.channel_id if old else channel_id,
                "twitch_user_id": old.twitch_user_id if old else user_id})
            if old and rule.username != old.username:
                raise ValueError("Account identity cannot be edited; remove the rule and resolve a new user.")
            if set(rule.command_ids) - valid_command_ids - (set(old.command_ids) if old else set()):
                raise ValueError("A selected command no longer exists. Refresh the list.")
            end = expiry(rule.expires_at)
            now = utcnow()
            if end is not None and not now < end <= now + MAX_DURATION:
                raise ValueError("Expiry must be in the future, within 366 days.")
            active = tuple(item for item in self._rules if item.active(now) and item.id != rule.id)
            if len(active) >= MAX_RULES:
                raise ValueError("At most 1000 active restrictions are supported.")
            self._save((*active, rule))

    def remove(self, identifier: object) -> None:
        with self._lock:
            self.get(identifier)
            self._save(tuple(rule for rule in self._rules if rule.id != identifier and rule.active(utcnow())))

    def _save(self, rules: tuple[CommandRestriction, ...]) -> None:
        def payload(rows):
            return {"version": 1, "restrictions": [{**asdict(row), "command_ids": list(row.command_ids)} for row in rows]}
        encoded = json.dumps(payload(rules), ensure_ascii=True, allow_nan=False, indent=2) + "\n"
        if len(encoded.encode("utf-8")) > MAX_FILE_BYTES:
            raise ValueError("Private restriction policy exceeds its storage limit.")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self._path.parent,
                    prefix=f".{self._path.name}.", suffix=".tmp", delete=False) as output:
                temporary = Path(output.name)
                output.write(encoded)
                output.flush()
                os.fsync(output.fileno())
            preserve_settings_recovery(self._path, payload(self._rules), version=1)
            temporary.replace(self._path)
            self._rules = rules
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
