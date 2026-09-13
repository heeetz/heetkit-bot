"""Repositories that isolate SQLAlchemy queries from services."""

from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.database.models import AIMemoryEntry, User, utcnow


class UserRepository:
    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._session_factory = session_factory

    async def get_by_twitch_user_id(self, twitch_user_id: str) -> User | None:
        async with self._session_factory() as session:
            statement = select(User).where(User.twitch_user_id == twitch_user_id)
            return await session.scalar(statement)

    async def upsert_seen(
        self,
        twitch_user_id: str,
        username: str,
        seen_at: datetime | None = None,
    ) -> User:
        current_time = seen_at or utcnow()
        async with self._session_factory() as session:
            statement = select(User).where(User.twitch_user_id == twitch_user_id)
            user = await session.scalar(statement)
            if user is None:
                user = User(
                    twitch_user_id=twitch_user_id,
                    username=username,
                    created_at=current_time,
                    last_seen_at=current_time,
                )
                session.add(user)
            else:
                user.username = username
                user.last_seen_at = current_time

            await session.commit()
            await session.refresh(user)
            return user

    async def get_by_username(self, username: str) -> User | None:
        async with self._session_factory() as session:
            statement = select(User).where(func.lower(User.username) == username.lower())
            return await session.scalar(statement)


class AIMemoryRepository:
    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._session_factory = session_factory

    async def get_recent(self, twitch_user_id: str, limit: int) -> list[AIMemoryEntry]:
        async with self._session_factory() as session:
            statement = (
                select(AIMemoryEntry)
                .where(AIMemoryEntry.twitch_user_id == twitch_user_id)
                .order_by(AIMemoryEntry.created_at.desc(), AIMemoryEntry.id.desc())
                .limit(limit)
            )
            entries = list((await session.scalars(statement)).all())
            return list(reversed(entries))

    async def append_and_prune(
        self,
        twitch_user_id: str,
        request_text: str,
        response_text: str,
        limit: int,
    ) -> None:
        async with self._session_factory() as session:
            session.add(
                AIMemoryEntry(
                    twitch_user_id=twitch_user_id,
                    request_text=request_text,
                    response_text=response_text,
                )
            )
            await session.flush()
            statement = (
                select(AIMemoryEntry.id)
                .where(AIMemoryEntry.twitch_user_id == twitch_user_id)
                .order_by(AIMemoryEntry.created_at.desc(), AIMemoryEntry.id.desc())
                .offset(limit)
            )
            old_ids = list((await session.scalars(statement)).all())
            if old_ids:
                await session.execute(
                    delete(AIMemoryEntry).where(AIMemoryEntry.id.in_(old_ids))
                )
            await session.commit()

    async def erase_for_user(self, twitch_user_id: str) -> None:
        async with self._session_factory() as session:
            await session.execute(
                delete(AIMemoryEntry).where(AIMemoryEntry.twitch_user_id == twitch_user_id)
            )
            await session.commit()
