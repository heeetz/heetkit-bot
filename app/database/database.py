"""Async SQLAlchemy database lifecycle."""

from pathlib import Path

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.database.models import Base


class Database:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        self.engine: AsyncEngine = create_async_engine(database_url)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

    async def initialize(self) -> None:
        self._create_sqlite_parent_directory()
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def close(self) -> None:
        await self.engine.dispose()

    def _create_sqlite_parent_directory(self) -> None:
        database_name = make_url(self._database_url).database
        if not self._database_url.startswith("sqlite") or not database_name or database_name == ":memory:":
            return
        Path(database_name).parent.mkdir(parents=True, exist_ok=True)
