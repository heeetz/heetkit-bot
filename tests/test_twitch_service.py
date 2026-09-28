"""Focused tests for cached Twitch API metadata."""

from types import SimpleNamespace

import pytest

from app.services.twitch import TwitchAPIService


class FakeTwitchClient:
    def __init__(self, categories: list[str | None]) -> None:
        self.categories = iter(categories)
        self.fetch_count = 0

    def fetch_streams(self, **kwargs):
        self.fetch_count += 1
        category = next(self.categories)

        async def streams():
            if category is not None:
                yield SimpleNamespace(game_name=category)

        return streams()


@pytest.mark.asyncio
async def test_current_category_is_cached_until_ttl_expires() -> None:
    now = 100.0
    client = FakeTwitchClient(["Counter-Strike 2", "Just Chatting"])
    service = TwitchAPIService(category_cache_ttl=90.0, clock=lambda: now)
    service.bind(client, channel_user_id="channel", token_user_id="bot")

    assert await service.get_current_category() == "Counter-Strike 2"
    now = 189.0
    assert await service.get_current_category() == "Counter-Strike 2"
    assert client.fetch_count == 1

    now = 190.0
    assert await service.get_current_category() == "Just Chatting"
    assert client.fetch_count == 2


@pytest.mark.asyncio
async def test_offline_category_result_is_cached() -> None:
    now = 100.0
    client = FakeTwitchClient([None, "Science & Technology"])
    service = TwitchAPIService(category_cache_ttl=90.0, clock=lambda: now)
    service.bind(client, channel_user_id="channel", token_user_id="bot")

    assert await service.get_current_category() is None
    now = 150.0
    assert await service.get_current_category() is None
    assert client.fetch_count == 1


@pytest.mark.asyncio
async def test_category_api_failure_returns_none_and_is_cached() -> None:
    class FailingClient:
        def __init__(self) -> None:
            self.fetch_count = 0

        def fetch_streams(self, **kwargs):
            self.fetch_count += 1
            raise RuntimeError("Twitch unavailable")

    now = 100.0
    client = FailingClient()
    service = TwitchAPIService(category_cache_ttl=90.0, clock=lambda: now)
    service.bind(client, channel_user_id="channel", token_user_id="bot")

    assert await service.get_current_category() is None
    now = 150.0
    assert await service.get_current_category() is None
    assert client.fetch_count == 1
