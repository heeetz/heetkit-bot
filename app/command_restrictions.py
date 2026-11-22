"""Installation-local access policy; never part of portable command configuration."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from uuid import uuid4, uuid5, NAMESPACE_URL

from app.errors import UserError
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
        raise UserError("command_restrictions.expiry_absolute_date_utc_offset") from None


@dataclass(frozen=True, slots=True)
class CommandRestriction:
    id: str
    channel_id: str | None
    twitch_user_id: str | None
    username: str
    command_ids: tuple[str, ...]
    expires_at: str | None
    note: str
    scope: str = "channel"
    legacy_ai: bool = False

    def active(self, now: datetime) -> bool:
        end = expiry(self.expires_at)
        return end is None or now < end


def parse_restriction(raw: object) -> CommandRestriction:
    fields = {"id", "channel_id", "twitch_user_id", "username", "command_ids", "expires_at", "note", "scope", "legacy_ai"}
    if not isinstance(raw, dict) or set(raw) != fields:
        raise UserError("command_restrictions.unexpected_or_missing_restriction_fields")
    scope, legacy = raw["scope"], raw["legacy_ai"]
    if scope not in ("channel", "global_ai") or type(legacy) is not bool:
        raise UserError("command_restrictions.select_channel_scope_global_ai_questions")
    if not isinstance(raw["id"], str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,40}", raw["id"]):
        raise UserError("command_restrictions.invalid_restriction_id")
    if (verified_user_id(raw["twitch_user_id"]) is None and not (legacy and raw["twitch_user_id"] is None)
            or scope == "channel" and verified_user_id(raw["channel_id"]) is None and not (legacy and raw["channel_id"] is None)
            or scope == "global_ai" and raw["channel_id"] is not None):
        raise UserError("command_restrictions.restrictions_require_verified_numeric_user_channel")
    ids = raw["command_ids"]
    if (not isinstance(ids, (list, tuple)) or len(ids) > 200
            or any(not isinstance(key, str) or not re.fullmatch(r"(?:custom:)?[a-zA-Z0-9_-]{1,64}", key)
                   or key == "optout" for key in ids) or len(set(ids)) != len(ids)):
        raise UserError("command_restrictions.select_valid_distinct_command_ids_optout")
    if (scope == "global_ai" or legacy) and list(ids) != ["ask"]:
        raise UserError("command_restrictions.global_ai_scope_migrated_ai_blocks")
    note = raw["note"]
    if not isinstance(note, str) or len(note) > 200 or any(ord(char) < 32 or ord(char) == 127 for char in note):
        raise UserError("command_restrictions.private_notes_one_line_most_200")
    try:
        note.encode("utf-8")
    except UnicodeError:
        raise UserError("command_restrictions.private_notes_contain_valid_unicode") from None
    end = expiry(raw["expires_at"])
    return CommandRestriction(raw["id"], raw["channel_id"], raw["twitch_user_id"],
        normalize_ai_username(raw["username"]), tuple(ids), end.isoformat() if end else None, note, scope, legacy)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise UserError("command_restrictions.duplicate_restriction_key")
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
                    or type(payload["version"]) is not int or payload["version"] != 2
                    or not isinstance(payload["restrictions"], list) or len(payload["restrictions"]) > MAX_RULES):
                raise ValueError
            rules = tuple(parse_restriction(row) for row in payload["restrictions"])
            if len({rule.id for rule in rules}) != len(rules):
                raise ValueError
            self._rules = rules
        except FileNotFoundError:
            return
        except (ValueError, UnicodeError, RecursionError):
            raise UserError("command_restrictions.invalid_command_restrictions_json_back_up") from None
        self.list()

    def list(self) -> tuple[CommandRestriction, ...]:
        with self._lock:
            active = tuple(rule for rule in self._rules if rule.active(utcnow()))
            if active != self._rules:
                self._save(active)
            return active

    def match(self, channel_id: str, user_id: str, command_id: str, username: str = "") -> CommandRestriction | None:
        with self._lock:
            now = utcnow()
            matches = [rule for rule in self._rules if (rule.scope == "global_ai" or rule.channel_id is None or rule.channel_id == channel_id)
                and (rule.twitch_user_id == user_id or rule.twitch_user_id is None and rule.username == username.lower())
                and (not rule.command_ids or command_id in rule.command_ids)
                and rule.active(now)]
            # Only authenticated chat identity can upgrade a legacy login fallback.
            if verified_user_id(user_id) and any(rule.twitch_user_id is None for rule in matches):
                updated = tuple(replace(rule, twitch_user_id=user_id) if rule in matches and rule.twitch_user_id is None else rule
                                for rule in self._rules)
                try:
                    self._save(updated)
                except (OSError, ValueError):
                    pass  # Compatibility matching still denies this request.
            # Report the widest remaining lifetime, including overlapping rules.
            return max(matches, key=lambda rule: expiry(rule.expires_at) or datetime.max.replace(tzinfo=timezone.utc), default=None)

    def get(self, identifier: object) -> CommandRestriction:
        with self._lock:
            for rule in self._rules:
                if rule.id == identifier and rule.active(utcnow()):
                    return rule
        raise UserError("command_restrictions.restriction_no_longer_exists_has_expired")

    def save(self, data: dict, *, channel_id: str, user_id: str, valid_command_ids: set[str]) -> None:
        with self._lock:
            old = self.get(data["id"]) if "id" in data else None
            scope = data.get("scope", old.scope if old else "channel")
            if old and scope != old.scope:
                raise UserError("command_restrictions.scope_cannot_edited_remove_rule_add")
            rule = parse_restriction({**data, "id": old.id if old else uuid4().hex, "scope": scope,
                "legacy_ai": old.legacy_ai if old else False,
                "channel_id": old.channel_id if old else channel_id,
                "twitch_user_id": (old.twitch_user_id or user_id) if old else user_id})
            if old and rule.username != old.username:
                raise UserError("command_restrictions.account_identity_cannot_edited_remove_rule")
            if set(rule.command_ids) - valid_command_ids - (set(old.command_ids) if old else set()):
                raise UserError("command_restrictions.selected_command_no_longer_exists_refresh")
            end = expiry(rule.expires_at)
            now = utcnow()
            if end is not None and not now < end <= now + MAX_DURATION:
                raise UserError("command_restrictions.expiry_future_within_366_days")
            active = tuple(item for item in self._rules if item.active(now) and item.id != rule.id)
            if len(active) >= MAX_RULES:
                raise UserError("command_restrictions.most_1000_active_restrictions_supported")
            self._save((*active, rule))

    def migrate_ai_blocks(self, blocks, channel_id):
        """Durable destination first; deterministic IDs make interrupted moves repeatable."""
        with self._lock:
            users = blocks.list()
            rules = self.migrated_ai_rules(users, channel_id)
            if rules != self._rules:
                self._save(rules)
            for user in users:
                blocks.unblock(user.username)

    def migrated_ai_rules(self, users, channel_id):
        with self._lock:
            channel_id = verified_user_id(channel_id)
            rules = tuple(replace(rule, channel_id=channel_id) if rule.legacy_ai and rule.channel_id is None
                          and rule.scope == "channel" and channel_id else rule for rule in self._rules)
            for user in users:
                identity = "id:" + user.twitch_user_id if user.twitch_user_id else "login:" + user.username
                identifier = uuid5(NAMESPACE_URL, "heetkit:legacy-ai:" + identity).hex
                if not any(rule.id == identifier for rule in rules):
                    rules = (*rules, CommandRestriction(identifier, channel_id, user.twitch_user_id,
                        user.username, ("ask",), None, "", legacy_ai=True))
            if len(rules) > MAX_RULES:
                raise UserError("command_restrictions.migrating_ai_blocks_exceeds_private_restriction")
            return rules

    def remove(self, identifier: object) -> None:
        with self._lock:
            self.get(identifier)
            self._save(tuple(rule for rule in self._rules if rule.id != identifier and rule.active(utcnow())))

    def _save(self, rules: tuple[CommandRestriction, ...]) -> None:
        def payload(rows):
            return {"version": 2, "restrictions": [{**asdict(row), "command_ids": list(row.command_ids)} for row in rows]}
        encoded = json.dumps(payload(rules), ensure_ascii=True, allow_nan=False, indent=2) + "\n"
        if len(encoded.encode("utf-8")) > MAX_FILE_BYTES:
            raise UserError("command_restrictions.private_restriction_policy_exceeds_storage_limit")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self._path.parent,
                    prefix=f".{self._path.name}.", suffix=".tmp", delete=False) as output:
                temporary = Path(output.name)
                output.write(encoded)
                output.flush()
                os.fsync(output.fileno())
            preserve_settings_recovery(self._path, payload(self._rules), version=2)
            temporary.replace(self._path)
            self._rules = rules
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
