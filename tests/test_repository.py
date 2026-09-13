"""Tests for the async user repository."""

from datetime import datetime, timedelta, timezone

import pytest

from app.database.database import Database
from app.database.repository import UserRepository


@pytest.mark.asyncio
async def test_user_repository_creates_and_updates_user() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.initialize()
    repository = UserRepository(database.session_factory)
    first_seen = datetime(2026, 1, 1, tzinfo=timezone.utc)
    second_seen = first_seen + timedelta(days=1)

    created = await repository.upsert_seen("42", "first_name", first_seen)
    updated = await repository.upsert_seen("42", "renamed", second_seen)
    found = await repository.get_by_twitch_user_id("42")

    assert created.id == updated.id
    assert updated.username == "renamed"
    assert found is not None
    assert found.last_seen_at == second_seen
    await database.close()