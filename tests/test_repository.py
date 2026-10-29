"""Tests for the async user repository."""

from datetime import timedelta

import pytest

from app.database.database import Database
from app.database.repository import UserRepository
from app.database.models import utcnow


@pytest.mark.asyncio
async def test_user_repository_creates_and_updates_user() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.initialize()
    repository = UserRepository(database.session_factory)
    first_seen = utcnow()
    second_seen = first_seen + timedelta(days=1)

    created = await repository.upsert_seen("42", "first_name", first_seen, channel_id="100")
    updated = await repository.upsert_seen("42", "renamed", second_seen, channel_id="100")
    found = await repository.get_by_twitch_user_id("42", channel_id="100")

    assert created.id == updated.id
    assert updated.username == "renamed"
    assert found is not None
    assert found.last_seen_at == second_seen
    await database.close()


@pytest.mark.asyncio
async def test_recent_usernames_excludes_old_users_and_ids() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.initialize()
    repository = UserRepository(database.session_factory)
    await repository.upsert_seen("old", "old_name", utcnow() - timedelta(hours=1), channel_id="100")
    await repository.upsert_seen("bot", "bot_name", utcnow(), channel_id="100")
    await repository.upsert_seen("recent", "recent_name", utcnow(), channel_id="100")

    assert await repository.recent_usernames(exclude_user_ids=("bot",), channel_id="100") == ["recent_name"]
    await database.close()
