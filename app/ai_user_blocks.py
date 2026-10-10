"""Profile-owned AI request blocks, keyed by verified ID or a fallback login."""

import json
import logging
import os
import re
import tempfile
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from threading import RLock

from app.settings_recovery import preserve_settings_recovery

logger = logging.getLogger(__name__)


def normalize_ai_username(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Enter a Twitch username.")
    username = value.strip().removeprefix("@").lower()
    if not re.fullmatch(r"[a-z0-9_]{1,25}", username):
        raise ValueError("Use a Twitch login of up to 25 letters, numbers or underscores.")
    return username


def verified_user_id(value: object) -> str | None:
    return value if isinstance(value, str) and re.fullmatch(r"[0-9]{1,20}", value) else None


@dataclass(frozen=True, slots=True)
class BlockedAIUser:
    username: str
    twitch_user_id: str | None = None


class AIUserBlocklist:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = RLock()
        self._users: tuple[BlockedAIUser, ...] = ()
        self._load()

    def list(self) -> tuple[BlockedAIUser, ...]:
        with self._lock:
            return self._users

    def is_blocked(self, user_id: str, username: str) -> bool:
        with self._lock:
            return any(
                user.twitch_user_id == user_id if user.twitch_user_id is not None
                else user.username == username.lower()
                for user in self._users
            )

    def block(self, username: object, user_id: str | None = None) -> None:
        username = normalize_ai_username(username)
        if user_id is not None and verified_user_id(user_id) is None:
            raise ValueError("Invalid Twitch account ID.")
        with self._lock:
            if any(user.username == username or (user_id is not None and user.twitch_user_id == user_id)
                   for user in self._users):
                raise ValueError("This Twitch user is already blocked from AI requests.")
            self._save((*self._users, BlockedAIUser(username, user_id)))

    def unblock(self, username: object) -> None:
        username = normalize_ai_username(username)
        with self._lock:
            if not any(user.username == username for user in self._users):
                raise ValueError("This Twitch user is not blocked.")
            self._save(tuple(user for user in self._users if user.username != username))

    def remember_observed_id(self, username: str, user_id: str) -> None:
        """Upgrade a fallback only from a verified Twitch chat account, never display text."""
        if verified_user_id(user_id) is None:
            return
        with self._lock:
            if any(user.twitch_user_id == user_id for user in self._users):
                return
            updated = tuple(replace(user, twitch_user_id=user_id)
                            if user.twitch_user_id is None and user.username == username.lower() else user
                            for user in self._users)
            if updated != self._users:
                self._save(updated)

    @staticmethod
    def _payload(users: tuple[BlockedAIUser, ...]) -> dict[str, object]:
        return {"version": 1, "users": [asdict(user) for user in users]}

    def _load(self) -> None:
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, UnicodeError, ValueError):
            logger.warning("Could not load AI user blocklist; profile file retained")
            return
        if not isinstance(payload, dict) or type(payload.get("version")) is not int or payload["version"] != 1 or not isinstance(payload.get("users"), list):
            logger.warning("Ignoring unsupported or malformed AI user blocklist; profile file retained")
            return
        users = []
        names, ids = set(), set()
        for raw in payload["users"]:
            try:
                if not isinstance(raw, dict):
                    raise ValueError("Invalid entry")
                username = normalize_ai_username(raw.get("username"))
                user_id = raw.get("twitch_user_id")
                if user_id is not None and verified_user_id(user_id) is None:
                    raise ValueError("Invalid account ID")
                if username in names or (user_id is not None and user_id in ids):
                    raise ValueError("Duplicate entry")
            except ValueError:
                logger.warning("Ignoring invalid AI user blocklist entry")
                continue
            users.append(BlockedAIUser(username, user_id))
            names.add(username)
            if user_id is not None:
                ids.add(user_id)
        self._users = tuple(users)

    def _save(self, users: tuple[BlockedAIUser, ...]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self._path.parent,
                                             prefix=f".{self._path.name}.", suffix=".tmp", delete=False) as output:
                temporary = Path(output.name)
                json.dump(self._payload(users), output, indent=2)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            preserve_settings_recovery(self._path, self._payload(self._users), version=1)
            temporary.replace(self._path)
            self._users = users
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
