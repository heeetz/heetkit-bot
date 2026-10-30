"""Async SQLAlchemy database lifecycle."""

import asyncio
import logging
from dataclasses import dataclass, field
from contextlib import suppress
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy import delete, select, event

from app.config.privacy import (AI_HISTORY_RETENTION_DAYS, RETENTION_CHECK_SECONDS, USER_RETENTION_DAYS,
                                AI_HISTORY_MAX_ENTRIES, AI_CONTEXT_MAX_ENTRIES, validate_memory_limits)
from app.database.models import AIMemoryEntry, PrivacyOptOut, User, utcnow
from app.database.migrations import SCHEMA_SQL, SCHEMA_VERSION, initialize_schema, maintain_recovery, DatabaseMigrationError, run_sqlite_work
from app.database.migrations import save_legacy_channel_mapping, validate_legacy_channel_choice
from app.desktop_instance import desktop_instance_guard, DesktopAlreadyRunningError


@dataclass
class MemoryPolicy:
    stored: int = AI_HISTORY_MAX_ENTRIES
    context: int = AI_CONTEXT_MAX_ENTRIES
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    privacy_epochs: dict[str, int] = field(default_factory=dict)


class Database:
    def __init__(self, database_url: str, *, history_limit=AI_HISTORY_MAX_ENTRIES, context_limit=AI_CONTEXT_MAX_ENTRIES) -> None:
        self._database_url = database_url
        stored, context = validate_memory_limits(history_limit, context_limit)
        self.memory_policy = MemoryPolicy(stored, context)
        name = make_url(database_url).database
        self.path = Path(name).resolve() if name and name != ":memory:" else None
        self._guard = None
        self._recovery_lock = asyncio.Lock()
        self.engine: AsyncEngine = create_async_engine(database_url)
        @event.listens_for(self.engine.sync_engine, "connect")
        def secure_delete(connection, _):
            connection.execute("PRAGMA secure_delete=ON")
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False,
                            info={"memory_policy": self.memory_policy, "database_path": self.path,
                                  "recovery_lock": self._recovery_lock})
        self._retention_task: asyncio.Task[None] | None = None

    async def initialize(self) -> None:
        self._create_sqlite_parent_directory()
        try:
            if self.path is not None:
                if self._guard is None:
                    guard = desktop_instance_guard(self.path, database=True)
                    guard.__enter__()
                    self._guard = guard
                report = await run_sqlite_work(initialize_schema, self.path, self.memory_policy.stored)
                if report:
                    logging.getLogger(__name__).info("Database migration verified: %s", report)
            else:
                async with self.engine.begin() as connection:
                    version = (await connection.exec_driver_sql("PRAGMA user_version")).scalar()
                    if version == 0:
                        for statement in SCHEMA_SQL:
                            await connection.exec_driver_sql(statement)
                        await connection.exec_driver_sql("INSERT INTO schema_metadata VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
                        await connection.exec_driver_sql(f"PRAGMA user_version={SCHEMA_VERSION}")
                    elif version != SCHEMA_VERSION:
                        raise DatabaseMigrationError("Unsupported database version.")
            await self.cleanup_expired()
        except BaseException as error:
            if self._guard is not None:
                self._guard.__exit__(type(error), error, error.__traceback__)
                self._guard = None
            if isinstance(error, DesktopAlreadyRunningError):
                raise DatabaseMigrationError("Database is in use; stop all profile processes before upgrading.") from None
            raise
        if self._retention_task is None:
            self._retention_task = asyncio.create_task(self._maintain_retention())

    async def cleanup_expired(self, now: datetime | None = None) -> None:
        """Delete expired data globally, including inactive viewers and memory-off profiles."""
        current_time = now or utcnow()
        async with self.session_factory() as session:
            opted_out = select(PrivacyOptOut.twitch_user_id)
            await session.execute(delete(AIMemoryEntry).where(
                (AIMemoryEntry.created_at <= current_time - timedelta(days=AI_HISTORY_RETENTION_DAYS))
                | AIMemoryEntry.twitch_user_id.in_(opted_out)
            ))
            await session.execute(delete(User).where(
                (User.last_seen_at <= current_time - timedelta(days=USER_RETENTION_DAYS))
                | User.twitch_user_id.in_(opted_out)
            ))
            await session.commit()
            suppression_ids = list((await session.scalars(opted_out)).all())
        from app.database.repository import AIMemoryRepository
        await AIMemoryRepository(self.session_factory).enforce_limit()
        if self.path is not None:
            async with self._recovery_lock:
                await run_sqlite_work(maintain_recovery, self.path, suppression_ids, now=current_time)

    async def configure_memory_limits(self, stored, context, *, persist=None):
        from app.database.repository import AIMemoryRepository
        await AIMemoryRepository(self.session_factory).configure_limits(stored, context, persist=persist)

    async def confirm_legacy_channel(self, channel_id, confirmed):
        validate_legacy_channel_choice(channel_id, confirmed)
        if self.path is None:
            raise DatabaseMigrationError("Legacy mapping requires an existing profile database.")
        try:
            with desktop_instance_guard(self.path, database=True):
                await run_sqlite_work(save_legacy_channel_mapping, self.path, channel_id)
        except DesktopAlreadyRunningError:
            raise DatabaseMigrationError("Database is in use. Stop the other profile process, then restart and confirm the channel.") from None

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
        try:
            await self.engine.dispose()
        finally:
            if self._guard is not None:
                self._guard.__exit__(None, None, None)
                self._guard = None

    def _create_sqlite_parent_directory(self) -> None:
        database_name = make_url(self._database_url).database
        if not self._database_url.startswith("sqlite") or not database_name or database_name == ":memory:":
            return
        Path(database_name).parent.mkdir(parents=True, exist_ok=True)
