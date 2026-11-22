"""Validated Twitch announcements and one connection-scoped scheduler."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from time import monotonic
from uuid import UUID, uuid4

from twitchio.exceptions import HTTPException

from app.errors import UserError
from typing import Annotated, Literal
from pydantic import AfterValidator, ConfigDict, Field, StrictBool, StrictInt, model_validator
from app.settings_models import SettingsModel, ControlFree, StreamAvailability, byte_limit, single_line, parse, field_value
from app.settings_recovery import preserve_settings_recovery
from app.twitch.sending import ChatSessionClosedError


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Announcement:
    id: str
    name: str
    enabled: bool
    messages: tuple[str, ...]
    message_mode: str
    interval_seconds: int
    min_messages: int
    stream_availability: str
    delivery_mode: str = "regular"

    def to_json(self) -> dict:
        return {**asdict(self), "messages": list(self.messages)}


class AnnouncementModel(SettingsModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    name: Annotated[ControlFree, byte_limit(80), AfterValidator(single_line)]
    enabled: StrictBool
    messages: Annotated[list[Annotated[ControlFree, byte_limit(450), AfterValidator(single_line)]], Field(strict=True, min_length=1, max_length=30)]
    message_mode: Literal["single", "random"]
    interval_seconds: Annotated[StrictInt, Field(ge=60, le=86400)]
    min_messages: Annotated[StrictInt, Field(ge=0, le=1000)]
    stream_availability: StreamAvailability
    delivery_mode: Literal["regular", "highlighted"] = "regular"

    @model_validator(mode="after")
    def message_count(self):
        if self.message_mode == "single" and len(self.messages) != 1:
            raise UserError("announcements.single_mode_requires_one_message_random")
        return self


def parse_announcements(payload: object, *, allow_new: bool = False) -> tuple[Announcement, ...]:
    rows = field_value(Annotated[list, Field(strict=True, max_length=50)], payload, "announcements")
    result, used = [], set()
    for raw in rows:
        if allow_new and isinstance(raw, dict) and raw.get("id") is None:
            raw = {**raw, "id": str(uuid4())}
        item = parse(AnnouncementModel, raw)
        identifier = str(item.id)
        if identifier in used:
            raise UserError("announcements.duplicate_announcement_id")
        used.add(identifier)
        values = item.model_dump(exclude={"id", "messages"})
        result.append(Announcement(id=identifier, messages=tuple(item.messages), **values))
    return tuple(result)


class AnnouncementStore:
    """Publish a complete immutable collection only after its atomic save."""

    def __init__(self, path: Path) -> None:
        self._path, self._lock = path, RLock()
        self._announcements: tuple[Announcement, ...] = ()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or set(payload) != {"version", "announcements"} or type(payload["version"]) is not int or payload["version"] != 1:
                raise UserError("announcements.unsupported_announcement_settings")
            self._announcements = parse_announcements(payload["announcements"])
        except FileNotFoundError:
            pass
        except (OSError, ValueError, UnicodeError):
            logger.warning("Could not load announcements; scheduled messages disabled.")

    def list(self) -> tuple[Announcement, ...]:
        with self._lock:
            return self._announcements

    def save(self, payload: object) -> None:
        with self._lock:
            parsed = parse_announcements(payload, allow_new=True)
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self._path.parent,
                        prefix=".announcements-", delete=False) as output:
                    temporary = Path(output.name)
                    json.dump({"version": 1, "announcements": [item.to_json() for item in parsed]}, output,
                              ensure_ascii=True, indent=2)
                    output.write("\n")
                    output.flush()
                    os.fsync(output.fileno())
                preserve_settings_recovery(self._path, {"version": 1,
                    "announcements": [item.to_json() for item in self._announcements]}, version=1)
                os.replace(temporary, self._path)
                self._announcements = parsed
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)


@dataclass(slots=True)
class ScheduleStatus:
    due: float
    baseline: int
    last_sent_at: str | None = None
    last_outcome: str | None = None


class AnnouncementScheduler:
    """One worker, no catch-up queue, and no output outside a captured session.

    Monotonic deadlines/activity are ephemeral. Every check consumes its window,
    including stream/activity skips and failed output. A fresh connection or saved
    collection starts a full interval with no inherited human activity.
    """

    def __init__(self, store, twitch, settings, state, *, clock=monotonic,
                 utcnow=lambda: datetime.now(timezone.utc), choose=random.choice) -> None:
        self.store, self.twitch, self.settings, self.state = store, twitch, settings, state
        self._clock, self._utcnow, self._choose = clock, utcnow, choose
        self._worker: asyncio.Task | None = None
        self._send: asyncio.Task | None = None
        self._sending_id: str | None = None
        self._poll: asyncio.Task | None = None
        self._closed = False
        self._statuses: dict[str, ScheduleStatus] = {}
        self._revision = 0
        self._stream_status, self._checked_at = "unknown", None
        self._next_poll = 0.0
        self._tick_lock = asyncio.Lock()
        self.twitch.on_chat_session_changed = self.reset

    def reset(self) -> None:
        self._revision += 1
        if self._send is not None and not self._send.done() and self._sending_id in self._statuses:
            self._statuses[self._sending_id].last_outcome = "cancelled"
        for task in (self._send, self._poll):
            if task is not None and not task.done():
                task.cancel()
        self._stream_status, self._checked_at = "unknown", None
        self._next_poll = 0.0
        now, count = self._clock(), self.twitch.human_messages
        previous = self._statuses
        self._statuses = {item.id: ScheduleStatus(now + item.interval_seconds, count,
            previous[item.id].last_sent_at if item.id in previous else None,
            previous[item.id].last_outcome if item.id in previous else None)
            for item in self.store.list()}

    def start(self) -> None:
        if self._worker is None and not self._closed:
            self.reset()
            self._worker = asyncio.create_task(self._run(), name="heetkit-announcements")

    def stream_status(self) -> str:
        if self.state.server_runtime:
            observe = self.state.server_stream_status
            return "unknown" if observe is None else observe()
        if self._checked_at is None or self._clock() - self._checked_at >= 135:
            return "unknown"
        return self._stream_status

    async def _poll_stream(self, revision: int) -> None:
        try:
            async with asyncio.timeout(15):
                live = await self.twitch.get_broadcaster_live(self.settings)
            status = "live" if live is True else "offline" if live is False else "unknown"
        except Exception:
            status = "unknown"
            try:
                await self.twitch.close_stream_monitor()
            except Exception:
                logger.warning("Announcement stream monitor cleanup failed.")
        if revision == self._revision:
            self._stream_status = status
            self._checked_at = self._clock() if status != "unknown" else None

    async def tick(self) -> None:
        # Also protects callers used by deterministic tests or host maintenance.
        async with self._tick_lock:
            if self._closed or not self.twitch.chat_connected:
                return
            items = self.store.list()
            now = self._clock()
            if (not self.state.server_runtime and now >= self._next_poll
                    and any(item.enabled and item.stream_availability != "anytime" for item in items)
                    and (self._poll is None or self._poll.done())):
                self._next_poll = now + 60
                self._poll = asyncio.create_task(self._poll_stream(self._revision))
            revision = self._revision
            # When schedules coincide, give never/least-recently delivered rows
            # first use of the ordinary limiter instead of starving later rows.
            for item in sorted(items, key=lambda row: self._statuses[row.id].last_sent_at or ""):
                if revision != self._revision or not self.twitch.chat_connected:
                    return
                status = self._statuses.get(item.id)
                now = self._clock()
                if not item.enabled or status is None or now < status.due:
                    continue
                count = self.twitch.human_messages
                eligible = count - status.baseline
                # Reschedule from NOW, never from an expired deadline.
                status.due, status.baseline = now + item.interval_seconds, count
                if eligible < item.min_messages:
                    status.last_outcome = "skipped_activity"
                    continue
                if item.stream_availability != "anytime" and self.stream_status() != {
                        "live_only": "live", "offline_only": "offline"}[item.stream_availability]:
                    status.last_outcome = "skipped_stream"
                    continue
                analytics = getattr(self.twitch, "analytics", None)
                channel_id = getattr(self.settings, "twitch_channel_user_id", "")
                if analytics is not None:
                    analytics.record("announcement.attempts", channel_id=channel_id, dimension=item.delivery_mode)
                sender = None
                try:
                    sender = self.twitch.announcement_sender() if item.delivery_mode == "highlighted" else self.twitch.chat_sender()
                    self._sending_id = item.id
                    self._send = asyncio.create_task(sender.reply(self._choose(item.messages)))
                    async with asyncio.timeout(15):
                        delivered = await self._send
                    status.last_outcome = "sent" if delivered else "not_confirmed"
                    if delivered:
                        status.last_sent_at = self._utcnow().isoformat()
                except asyncio.CancelledError:
                    if asyncio.current_task().cancelling():
                        raise
                    status.last_outcome = "cancelled"
                except ChatSessionClosedError:
                    status.last_outcome = "cancelled"
                except HTTPException as error:
                    status.last_outcome = ({401: "authorization_required", 403: "permission_denied"}.get(error.status, "failed")
                        if item.delivery_mode == "highlighted" else "failed")
                    logger.warning("Scheduled send rejected; waiting for the next interval.")
                except Exception:
                    status.last_outcome = "failed"
                    logger.warning("Scheduled chat send failed; waiting for the next interval.")
                finally:
                    if analytics is not None:
                        outcome = getattr(sender, "last_outcome", None)
                        terminal = ("sent" if outcome == "confirmed_send" else
                                    "uncertain" if outcome == "uncertain_send" else "failed")
                        analytics.record("announcement." + terminal, channel_id=channel_id, dimension=item.delivery_mode)
                    self._send = None
                    self._sending_id = None

    def snapshot(self) -> list[dict]:
        now, utc = self._clock(), self._utcnow()
        rows = []
        for item in self.store.list():
            status = self._statuses.get(item.id)
            connected = item.enabled and self.twitch.chat_connected and not self._closed
            rows.append({**item.to_json(), "status": {
                "next_run_at": (utc + timedelta(seconds=max(0, status.due - now))).isoformat()
                    if status is not None and connected else None,
                "last_sent_at": status.last_sent_at if status else None,
                "last_outcome": status.last_outcome if status else None,
                "eligible_messages": max(0, self.twitch.human_messages - status.baseline)
                    if status is not None and connected else 0,
            }})
        return rows

    async def _run(self) -> None:
        while True:
            await self.tick()
            await asyncio.sleep(1)

    async def close(self) -> None:
        self._closed = True
        self.reset()
        tasks = [task for task in (self._worker, self._send, self._poll) if task is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if not self.state.server_runtime:
            await self.twitch.close_stream_monitor()
