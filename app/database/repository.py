"""Repositories that isolate SQLAlchemy queries from services."""

from datetime import datetime, timedelta

from sqlalchemy import delete, exists, func, insert, literal, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config.privacy import AI_HISTORY_RETENTION_DAYS, USER_RETENTION_DAYS
from app.database.models import AIMemoryEntry, PrivacyOptOut, User, utcnow


def storage_allowed(twitch_user_id: str):
    return ~exists().where(PrivacyOptOut.twitch_user_id == twitch_user_id)


class UserRepository:
    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._session_factory = session_factory

    async def is_storage_opted_out(self, twitch_user_id: str) -> bool:
        async with self._session_factory() as session:
            return await session.get(PrivacyOptOut, twitch_user_id) is not None

    async def get_by_twitch_user_id(self, twitch_user_id: str) -> User | None:
        async with self._session_factory() as session:
            statement = select(User).where(
                User.twitch_user_id == twitch_user_id,
                User.last_seen_at > utcnow() - timedelta(days=USER_RETENTION_DAYS),
                storage_allowed(twitch_user_id),
            )
            return await session.scalar(statement)

    async def upsert_seen(
        self,
        twitch_user_id: str,
        username: str,
        seen_at: datetime | None = None,
    ) -> User | None:
        current_time = seen_at or utcnow()
        async with self._session_factory() as session:
            statement = select(User).where(User.twitch_user_id == twitch_user_id)
            user = await session.scalar(statement)
            if user is None:
                await session.execute(
                    insert(User).from_select(
                        ["twitch_user_id", "username", "created_at", "last_seen_at"],
                        select(
                            literal(twitch_user_id), literal(username),
                            literal(current_time, type_=User.created_at.type),
                            literal(current_time, type_=User.last_seen_at.type),
                        ).where(storage_allowed(twitch_user_id)),
                    )
                )
            else:
                await session.execute(
                    update(User).where(
                        User.twitch_user_id == twitch_user_id,
                        storage_allowed(twitch_user_id),
                    ).values(username=username, last_seen_at=current_time)
                )

            await session.commit()
            return await session.scalar(
                select(User).where(
                    User.twitch_user_id == twitch_user_id, storage_allowed(twitch_user_id),
                ).execution_options(populate_existing=True)
            )

    async def get_by_username(self, username: str) -> User | None:
        async with self._session_factory() as session:
            statement = select(User).where(
                func.lower(User.username) == username.lower(),
                User.last_seen_at > utcnow() - timedelta(days=USER_RETENTION_DAYS),
                storage_allowed(User.twitch_user_id),
            )
            return await session.scalar(statement)

    async def recent_usernames(self, *, exclude_user_ids: tuple[str, ...] = (), limit: int = 50) -> list[str]:
        """Recent chatters eligible for a random-user template variable."""
        async with self._session_factory() as session:
            statement = (
                select(User.username)
                .where(User.last_seen_at >= utcnow() - timedelta(minutes=30))
                .where(storage_allowed(User.twitch_user_id))
                .order_by(User.last_seen_at.desc())
                .limit(limit)
            )
            if exclude_user_ids:
                statement = statement.where(User.twitch_user_id.not_in(exclude_user_ids))
            return list((await session.scalars(statement)).all())


class AIMemoryRepository:
    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._session_factory = session_factory

    async def get_recent(self, twitch_user_id: str, limit: int) -> list[AIMemoryEntry]:
        async with self._session_factory() as session:
            statement = (
                select(AIMemoryEntry)
                .where(AIMemoryEntry.twitch_user_id == twitch_user_id)
                .where(
                    AIMemoryEntry.created_at > utcnow() - timedelta(days=AI_HISTORY_RETENTION_DAYS),
                    storage_allowed(twitch_user_id),
                )
                .order_by(AIMemoryEntry.created_at.desc(), AIMemoryEntry.id.desc())
                .limit(limit)
            )
            entries = list((await session.scalars(statement)).all())
            return list(reversed(entries))

    async def append(
        self,
        twitch_user_id: str,
        request_text: str,
        response_text: str,
    ) -> None:
        async with self._session_factory() as session:
            await session.execute(
                insert(AIMemoryEntry).from_select(
                    ["twitch_user_id", "request_text", "response_text", "created_at"],
                    select(
                        literal(twitch_user_id), literal(request_text), literal(response_text),
                        literal(utcnow(), type_=AIMemoryEntry.created_at.type),
                    ).where(storage_allowed(twitch_user_id)),
                )
            )
            await session.commit()

    async def erase_for_user(self, twitch_user_id: str) -> None:
        async with self._session_factory() as session:
            await session.execute(
                delete(AIMemoryEntry).where(AIMemoryEntry.twitch_user_id == twitch_user_id)
            )
            await session.commit()
