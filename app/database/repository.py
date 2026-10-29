"""Channel-scoped personal storage; suppression always spans the whole profile."""

from datetime import datetime, timedelta

from sqlalchemy import case, delete, exists, func, insert, literal, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config.privacy import AI_HISTORY_RETENTION_DAYS, USER_RETENTION_DAYS, validate_memory_limits
from app.database.models import AIMemoryEntry, PrivacyOptOut, User, utcnow
from app.database.migrations import maintain_recovery, run_sqlite_work


def storage_allowed(twitch_user_id: str):
    return ~exists().where(PrivacyOptOut.twitch_user_id == twitch_user_id)


def valid_channel_id(value: str) -> bool:
    return isinstance(value, str) and value.isascii() and value.isdigit() and 1 <= len(value) <= 32


class UserRepository:
    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._session_factory = session_factory
        self._suppressed_ids: set[str] = set()

    def logs_suppressed(self, twitch_user_id: str) -> bool:
        """Synchronous signal for requests already awaiting a provider/send."""
        return twitch_user_id in self._suppressed_ids

    async def is_storage_opted_out(self, twitch_user_id: str) -> bool:
        async with self._session_factory() as session:
            suppressed = await session.get(PrivacyOptOut, twitch_user_id) is not None
        if suppressed:
            self._suppressed_ids.add(twitch_user_id)
        return suppressed or self.logs_suppressed(twitch_user_id)

    async def opt_out(self, twitch_user_id: str) -> None:
        if not twitch_user_id.isascii() or not twitch_user_id.isdigit() or not 1 <= len(twitch_user_id) <= 32:
            raise ValueError("Opt-out requires the authenticated Twitch account ID.")
        # Fail closed for diagnostics even if persistence later needs operator help.
        self._suppressed_ids.add(twitch_user_id)
        async with self._session_factory() as session:
            await session.execute(sqlite_insert(PrivacyOptOut).values(twitch_user_id=twitch_user_id).on_conflict_do_nothing())
            await session.execute(delete(User).where(User.twitch_user_id == twitch_user_id))
            await session.execute(delete(AIMemoryEntry).where(AIMemoryEntry.twitch_user_id == twitch_user_id))
            await session.commit()
        path = self._session_factory.kw["info"]["database_path"]
        if path is not None:
            async with self._session_factory.kw["info"]["recovery_lock"]:
                await run_sqlite_work(maintain_recovery, path, (twitch_user_id,))

    async def get_by_twitch_user_id(self, twitch_user_id: str, *, channel_id: str) -> User | None:
        async with self._session_factory() as session:
            return await session.scalar(select(User).where(
                User.channel_id == channel_id, User.twitch_user_id == twitch_user_id,
                User.last_seen_at > utcnow() - timedelta(days=USER_RETENTION_DAYS), storage_allowed(twitch_user_id)))

    async def upsert_seen(self, twitch_user_id: str, username: str, seen_at: datetime | None = None,
                          *, channel_id: str) -> User | None:
        if not valid_channel_id(channel_id):
            return None
        current_time = seen_at or utcnow()
        async with self._session_factory() as session:
            statement = sqlite_insert(User).from_select(
                ["channel_id", "twitch_user_id", "username", "created_at", "last_seen_at"],
                select(literal(channel_id), literal(twitch_user_id), literal(username),
                       literal(current_time, type_=User.created_at.type), literal(current_time, type_=User.last_seen_at.type))
                .where(storage_allowed(twitch_user_id)))
            # Membership is (channel, stable ID), including after a rename. An
            # expired membership starts a new retained observation period.
            statement = statement.on_conflict_do_update(index_elements=[User.channel_id, User.twitch_user_id],
                set_={"username": username, "created_at": case(
                    (User.last_seen_at <= current_time - timedelta(days=USER_RETENTION_DAYS), current_time), else_=User.created_at),
                    "last_seen_at": current_time}, where=storage_allowed(twitch_user_id))
            await session.execute(statement)
            await session.commit()
            return await session.scalar(select(User).where(User.channel_id == channel_id,
                User.twitch_user_id == twitch_user_id, storage_allowed(twitch_user_id)))

    async def get_by_username(self, username: str, *, channel_id: str) -> User | None:
        async with self._session_factory() as session:
            return await session.scalar(select(User).where(User.channel_id == channel_id,
                func.lower(User.username) == username.lower(),
                User.last_seen_at > utcnow() - timedelta(days=USER_RETENTION_DAYS), storage_allowed(User.twitch_user_id))
                .order_by(User.last_seen_at.desc()))

    async def recent_usernames(self, *, channel_id: str, exclude_user_ids: tuple[str, ...] = (), limit: int = 50) -> list[str]:
        async with self._session_factory() as session:
            statement = (select(User.username).where(User.channel_id == channel_id,
                User.last_seen_at >= utcnow() - timedelta(minutes=30), storage_allowed(User.twitch_user_id))
                .order_by(User.last_seen_at.desc()).limit(limit))
            if exclude_user_ids:
                statement = statement.where(User.twitch_user_id.not_in(exclude_user_ids))
            return list((await session.scalars(statement)).all())


class AIMemoryRepository:
    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._session_factory = session_factory
        self.policy = session_factory.kw["info"]["memory_policy"]

    async def get_recent(self, twitch_user_id: str, limit: int, *, channel_id: str) -> list[AIMemoryEntry]:
        async with self._session_factory() as session:
            statement = (select(AIMemoryEntry).where(AIMemoryEntry.channel_id == channel_id,
                AIMemoryEntry.twitch_user_id == twitch_user_id,
                AIMemoryEntry.created_at > utcnow() - timedelta(days=AI_HISTORY_RETENTION_DAYS), storage_allowed(twitch_user_id))
                .order_by(AIMemoryEntry.created_at.desc(), AIMemoryEntry.id.desc()).limit(min(limit, self.policy.stored)))
            return list(reversed(list((await session.scalars(statement)).all())))

    @staticmethod
    async def _prune(session, limit):
        ranked = select(AIMemoryEntry.id, func.row_number().over(
            partition_by=(AIMemoryEntry.channel_id, AIMemoryEntry.twitch_user_id),
            order_by=(AIMemoryEntry.created_at.desc(), AIMemoryEntry.id.desc())).label("position")).subquery()
        await session.execute(delete(AIMemoryEntry).where(AIMemoryEntry.id.in_(select(ranked.c.id).where(ranked.c.position > limit))))

    async def enforce_limit(self):
        async with self.policy.lock, self._session_factory() as session:
            await self._prune(session, self.policy.stored)
            await session.commit()

    async def configure_limits(self, stored, context, *, persist=None):
        stored, context = validate_memory_limits(stored, context)
        async with self.policy.lock, self._session_factory() as session:
            await self._prune(session, stored)
            # A saved lower cap must never precede the actual deletion. If the
            # settings save fails, the old policy remains; removed history stays removed.
            await session.commit()
            if persist is not None:
                persist()
            self.policy.stored, self.policy.context = stored, context

    async def append(self, twitch_user_id: str, request_text: str, response_text: str, *, channel_id: str) -> None:
        if not valid_channel_id(channel_id):
            return
        async with self.policy.lock, self._session_factory() as session:
            await session.execute(insert(AIMemoryEntry).from_select(
                ["channel_id", "twitch_user_id", "request_text", "response_text", "created_at"],
                select(literal(channel_id), literal(twitch_user_id), literal(request_text), literal(response_text),
                       literal(utcnow(), type_=AIMemoryEntry.created_at.type)).where(storage_allowed(twitch_user_id))))
            await self._prune(session, self.policy.stored)
            await session.commit()

    async def erase_for_user(self, twitch_user_id: str, *, channel_id: str) -> None:
        async with self._session_factory() as session:
            await session.execute(delete(AIMemoryEntry).where(AIMemoryEntry.channel_id == channel_id,
                                                           AIMemoryEntry.twitch_user_id == twitch_user_id))
            await session.commit()
