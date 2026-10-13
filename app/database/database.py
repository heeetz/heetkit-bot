"""Async SQLAlchemy database lifecycle."""

import asyncio
import logging
from contextlib import suppress
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy import delete, select

from app.config.privacy import AI_HISTORY_RETENTION_DAYS, RETENTION_CHECK_SECONDS, USER_RETENTION_DAYS
from app.database.models import AIMemoryEntry, Base, PrivacyOptOut, User, utcnow


class Database:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        self.engine: AsyncEngine = create_async_engine(database_url)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)
        self._retention_task: asyncio.Task[None] | None = None

    async def initialize(self) -> None:
        self._create_sqlite_parent_directory()
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        await self.cleanup_expired()
        if self._retention_task is None:
            self._retention_task = asyncio.create_task(self._maintain_retention())

    async def cleanup_expired(self, now: datetime | None = None) -> None:
        """Delete expired data globally, including inactive viewers and memory-off profiles."""
        current_time = now or utcnow()
        async with self.session_factory() as session:
            expired_users = select(User.twitch_user_id).where(
                User.last_seen_at <= current_time - timedelta(days=USER_RETENTION_DAYS)
            )
            opted_out = select(PrivacyOptOut.twitch_user_id)
            await session.execute(delete(AIMemoryEntry).where(
                (AIMemoryEntry.created_at <= current_time - timedelta(days=AI_HISTORY_RETENTION_DAYS))
                | AIMemoryEntry.twitch_user_id.in_(expired_users)
                | AIMemoryEntry.twitch_user_id.in_(opted_out)
            ))
            await session.execute(delete(User).where(
                User.twitch_user_id.in_(expired_users) | User.twitch_user_id.in_(opted_out)
            ))
            await session.commit()

    async def _maintain_retention(self) -> None:
        while True:
            await asyncio.sleep(RETENTION_CHECK_SECONDS)
            try:
                await self.cleanup_expired()
            except Exception as error:
                # SQLAlchemy exception text can contain bound personal data.
                logging.getLogger(__name__).error("Privacy retention cleanup failed: %s", type(error).__name__)

    async def close(self) -> None:
        if self._retention_task is not None:
            self._retention_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._retention_task
            self._retention_task = None
        await self.engine.dispose()

    def _create_sqlite_parent_directory(self) -> None:
        database_name = make_url(self._database_url).database
        if not self._database_url.startswith("sqlite") or not database_name or database_name == ":memory:":
            return
        Path(database_name).parent.mkdir(parents=True, exist_ok=True)
