"""Private observed chat counts for the current month and latest broadcast."""

import asyncio
from datetime import datetime, timedelta, timezone
import json
import logging

from sqlalchemy import and_, delete, func, literal, select, text, update
from sqlalchemy.dialects.sqlite import insert

from app.ai_user_blocks import normalize_ai_username
from app.config.privacy import USER_RETENTION_DAYS
from app.database.models import LeaderboardCount as Count, LeaderboardPeriod as Period
from app.database.models import LeaderboardSettings, PrivacyOptOut, User, utcnow
from app.database.repository import valid_channel_id

POLL_SECONDS = 20
POLL_TIMEOUT = 10
logger = logging.getLogger(__name__)


def month_window(now: datetime):
    start = now.astimezone(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = start.replace(year=start.year + (start.month == 12), month=start.month % 12 + 1)
    return start.strftime("%Y-%m"), start, end


class Leaderboards:
    def __init__(self, users, twitch, settings, *, clock=utcnow):
        self.users = users
        self.sessions = users._session_factory
        self.twitch = twitch
        self.settings = settings
        self.clock = clock
        self._changed = asyncio.Event()
        self._worker = None
        self._session = None
        self._coverage_from = None
        self._stream_id = None
        self._stream_from = None
        self._counting_enabled = True
        self._collection_epoch = 0
        self.stream_status = "unknown"

    @property
    def counting_enabled(self):
        return self._counting_enabled

    async def start(self):
        if self._worker is not None:
            return
        # A process exit cannot confirm the unclosed polling interval.
        async with self.users.policy.lock, self.sessions() as session:
            saved = await session.scalar(text(
                "SELECT value FROM schema_metadata WHERE name = 'leaderboard_counting_enabled'"))
            await session.execute(delete(Count).where(Count.kind == "pending"))
            await session.commit()
            self._counting_enabled = saved != "0"
            self.connection_changed()
        self._worker = asyncio.create_task(self._monitor(), name="heetkit-leaderboards")

    async def close(self):
        if self._worker is not None:
            self._worker.cancel()
            await asyncio.gather(self._worker, return_exceptions=True)
            self._worker = None

    def connection_changed(self):
        self._collection_epoch += 1
        self._session = None
        self._coverage_from = (
            self.clock() if self.counting_enabled and self.twitch.leaderboard_connection()[1] is not None else None
        )
        self._stream_id = self._stream_from = None
        self.stream_status = "unknown"
        self._changed.set()

    async def configure_counting(self, enabled: bool):
        if type(enabled) is not bool:
            raise ValueError("Count chat messages must be a boolean.")
        async with self.users.policy.lock, self.sessions() as session:
            if enabled == self.counting_enabled:
                return
            await session.execute(text(
                "INSERT INTO schema_metadata (name, value) VALUES ('leaderboard_counting_enabled', :value) "
                "ON CONFLICT(name) DO UPDATE SET value = excluded.value"), {"value": "1" if enabled else "0"})
            if not enabled:
                now = self.clock()
                await session.execute(update(Period).where(
                    (Period.ends_at > now) | Period.ends_at.is_(None)).values(partial=1))
                # The polling interval is unconfirmed once collection stops.
                await session.execute(delete(Count).where(Count.kind == "pending"))
            await session.commit()
            self._counting_enabled = enabled
            self.connection_changed()

    async def _monitor(self):
        while True:
            self._changed.clear()
            channel, chat_session = self.twitch.leaderboard_connection()
            if not self.counting_enabled or chat_session is None:
                await self._changed.wait()
                continue
            epoch = self._collection_epoch
            try:
                async with asyncio.timeout(POLL_TIMEOUT):
                    stream = await self.twitch.fetch_connected_broadcast(channel, chat_session)
                if epoch != self._collection_epoch:
                    continue
                if stream is not None and (not isinstance(stream.id, str) or not stream.id
                                           or not isinstance(stream.started_at, datetime) or stream.started_at.tzinfo is None
                                           or stream.started_at > self.clock()):
                    raise ValueError("Invalid broadcast observation")
                await self._observe(channel, chat_session, stream)
            except Exception:
                if epoch != self._collection_epoch:
                    continue
                try:
                    await self._observe(channel, chat_session, None, failed=True)
                except Exception:
                    if epoch == self._collection_epoch:
                        self._session = self._stream_id = self._stream_from = None
                        self.stream_status = "unknown"
                    logger.warning("Could not record leaderboard coverage")
            try:
                await asyncio.wait_for(self._changed.wait(), POLL_SECONDS)
            except TimeoutError:
                pass

    async def _observe(self, channel, chat_session, stream, *, failed=False):
        epoch = self._collection_epoch
        async with self.users.policy.lock, self.sessions() as session:
            if (not self.counting_enabled or epoch != self._collection_epoch
                    or self.twitch.leaderboard_connection() != (channel, chat_session)):
                return
            now = self.clock()
            month = await self._month(session, channel, now)
            if self._session is not chat_session:
                month.partial = 1
            previous = await session.get(Period, (channel, "stream"))
            if (stream is not None and previous is not None and stream.id != previous.period_id
                    and stream.started_at < previous.started_at):
                # An older Twitch observation can arrive after a new broadcast is known.
                stream, failed = None, True
            broadcast = stream.id if stream is not None else None
            confirmed = (broadcast is not None and previous is not None and previous.period_id == broadcast
                         and self._stream_id == broadcast and self._session is chat_session
                         and (now - self._stream_from).total_seconds() <= POLL_SECONDS + POLL_TIMEOUT + 2)
            if confirmed:
                pending = select(Count.channel_id, literal("stream"), Count.period_id,
                                 Count.twitch_user_id, Count.messages).where(
                    Count.channel_id == channel, Count.kind == "pending", Count.period_id == broadcast,
                    ~select(PrivacyOptOut.twitch_user_id).where(
                        PrivacyOptOut.twitch_user_id == Count.twitch_user_id).exists(),
                )
                add = insert(Count).from_select(
                    ["channel_id", "kind", "period_id", "twitch_user_id", "messages"], pending)
                await session.execute(add.on_conflict_do_update(set_={"messages": Count.messages + add.excluded.messages}))
            elif previous is not None and previous.ends_at is None:
                previous.partial = 1
            await session.execute(delete(Count).where(Count.channel_id == channel, Count.kind == "pending"))
            if broadcast is not None and (previous is None or previous.period_id != broadcast):
                await session.execute(delete(Count).where(Count.channel_id == channel, Count.kind == "stream"))
                if previous is None:
                    previous = Period(channel_id=channel, kind="stream")
                    session.add(previous)
                previous.period_id, previous.started_at = broadcast, stream.started_at
                previous.partial = int(stream.started_at < now)
            if previous is not None and not failed:
                previous.ends_at = None if broadcast else previous.ends_at or now
            await session.commit()
            if epoch != self._collection_epoch or self.twitch.leaderboard_connection() != (channel, chat_session):
                return
            self._session = chat_session
            self._stream_id = broadcast
            self._stream_from = now if broadcast else None
            self.stream_status = "unknown" if failed else "live" if broadcast else "offline"

    async def _month(self, session, channel, now):
        period = await session.get(Period, (channel, "month"))
        if period is None or now >= period.ends_at:
            if not self.counting_enabled:
                return None
            name, start, end = month_window(now)
            connected_channel, chat_session = self.twitch.leaderboard_connection()
            partial = (connected_channel != channel or chat_session is None
                       or self._coverage_from is None or self._coverage_from > start)
            await session.execute(delete(Count).where(Count.channel_id == channel, Count.kind == "month"))
            if period is None:
                period = Period(channel_id=channel, kind="month")
                session.add(period)
            period.period_id = name
            period.started_at, period.ends_at = start, end
            period.partial = int(partial)
        return period

    def capture(self, message):
        if not self.counting_enabled:
            return None
        channel, chat_session = self.twitch.leaderboard_connection()
        if (chat_session is None or chat_session is not message.send_session or channel != message.channel_id
                or self._coverage_from is None or not valid_channel_id(message.author.twitch_user_id)):
            return None
        observed_at = message.observed_at
        if (not isinstance(observed_at, datetime) or observed_at.tzinfo is None
                or not self._coverage_from <= observed_at <= self.clock()):
            return None
        stream_id = (self._stream_id if self._session is chat_session and self._stream_from is not None
                     and self._stream_from <= observed_at else None)
        epoch = self._collection_epoch

        async def write(session):
            if (epoch != self._collection_epoch
                    or self.twitch.leaderboard_connection() != (channel, chat_session)):
                return
            user, name = message.author.twitch_user_id, message.author.username.casefold()
            configured = await session.get(LeaderboardSettings, channel)
            exclusions = json.loads(configured.exclusions) if configured else {}
            if name in exclusions and exclusions[name] is None:
                exclusions[name] = user  # The chat event verifies the login and account ID.
                configured.exclusions = json.dumps(exclusions)
            if user == self.settings.twitch_bot_user_id or user in exclusions.values():
                return
            month = await self._month(session, channel, self.clock())
            if month.started_at <= observed_at < month.ends_at:
                await self._increment(session, channel, "month", month.period_id, user)
            if (stream_id and self._stream_id == stream_id and self._stream_from is not None
                    and 0 <= (observed_at - self._stream_from).total_seconds() <= POLL_SECONDS + POLL_TIMEOUT):
                await self._increment(session, channel, "pending", stream_id, user)

        return write

    @staticmethod
    async def _increment(session, channel, kind, period, user):
        statement = insert(Count).values(channel_id=channel, kind=kind, period_id=period,
                                         twitch_user_id=user, messages=1)
        await session.execute(statement.on_conflict_do_update(set_={"messages": Count.messages + 1}))

    def _ranked(self, period, excluded):
        ids = [user for user in excluded.values() if user is not None]
        if valid_channel_id(self.settings.twitch_bot_user_id):
            ids.append(self.settings.twitch_bot_user_id)
        names = [name for name, user in excluded.items() if user is None]
        return (select(Count.twitch_user_id, User.username, Count.messages,
                       func.rank().over(order_by=Count.messages.desc()).label("place"))
                .join(User, and_(User.channel_id == Count.channel_id, User.twitch_user_id == Count.twitch_user_id))
                .where(Count.channel_id == period.channel_id, Count.kind == period.kind,
                       Count.period_id == period.period_id, Count.twitch_user_id.not_in(ids),
                       User.last_seen_at > self.clock() - timedelta(days=USER_RETENTION_DAYS),
                       func.lower(User.username).not_in(names),
                       ~select(PrivacyOptOut.twitch_user_id).where(
                           PrivacyOptOut.twitch_user_id == Count.twitch_user_id).exists()).subquery())

    async def _rows(self, session, period, exclusions, limit, user=None):
        if period is None:
            return []
        ranked = self._ranked(period, exclusions)
        statement = select(ranked).order_by(ranked.c.place, ranked.c.twitch_user_id).limit(limit)
        if user is not None:
            statement = statement.where(ranked.c.twitch_user_id == user)
        return [{"place": row.place, "nickname": row.username, "messages": row.messages}
                for row in await session.execute(statement) if not self.users.logs_suppressed(row.twitch_user_id)]

    async def monthly(self, channel, *, limit=1, user=None):
        if not valid_channel_id(channel) or (user is not None and self.users.logs_suppressed(user)):
            return []
        async with self.users.policy.lock, self.sessions() as session:
            settings = await session.get(LeaderboardSettings, channel)
            period = await self._month(session, channel, self.clock())
            rows = await self._rows(session, period, json.loads(settings.exclusions) if settings else {}, limit, user)
            await session.commit()
            return rows if user is None or not self.users.logs_suppressed(user) else []

    async def snapshot(self, channel):
        if not valid_channel_id(channel):
            return None
        async with self.users.policy.lock, self.sessions() as session:
            settings = await session.get(LeaderboardSettings, channel)
            exclusions = json.loads(settings.exclusions) if settings else {}
            month = await self._month(session, channel, self.clock())
            stream = await session.get(Period, (channel, "stream"))
            connected = self.twitch.leaderboard_connection()[0] == channel
            result = {"channel_id": channel, "connected": connected,
                      "stream_status": self.stream_status if connected else "unknown",
                      "exclusions": list(exclusions)}
            for period in (month, stream):
                if period is not None:
                    result[period.kind] = {
                        "period": period.period_id,
                        "started_at": period.started_at.isoformat(),
                        "ends_at": period.ends_at.isoformat() if period.ends_at else None,
                        "partial": bool(period.partial or (not connected and period.ends_at is None)
                                        or (not connected and period.kind == "month")),
                        "rows": await self._rows(session, period, exclusions, 10),
                    }
            await session.commit()
            return result

    async def configure(self, channel, names):
        if not valid_channel_id(channel):
            raise ValueError("Choose a Twitch channel first.")
        if not isinstance(names, list) or len(names) > 50:
            raise ValueError("Enter up to 50 bot nicknames.")
        names = list(dict.fromkeys(normalize_ai_username(name) for name in names))
        async with self.users.policy.lock, self.sessions() as session:
            settings = await session.get(LeaderboardSettings, channel)
            existing = json.loads(settings.exclusions) if settings else {}
            exclusions = {name: existing.get(name) for name in names}
            unresolved = [name for name in names if exclusions[name] is None]
            if unresolved:
                rows = await session.execute(select(func.lower(User.username), User.twitch_user_id).where(
                    User.channel_id == channel, func.lower(User.username).in_(unresolved),
                    User.last_seen_at > self.clock() - timedelta(days=USER_RETENTION_DAYS)).order_by(User.last_seen_at))
                exclusions.update({name: user for name, user in rows})
            if settings is None:
                settings = LeaderboardSettings(channel_id=channel)
                session.add(settings)
            settings.exclusions = json.dumps(exclusions)
            await session.commit()
