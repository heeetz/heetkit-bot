"""Focused tests for cached Twitch API metadata."""

from types import SimpleNamespace

import pytest

from app.services.twitch import TwitchAPIService
from app.config.settings import Settings


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
async def test_authorization_delegates_only_to_the_bound_bot() -> None:
    service = TwitchAPIService()
    with pytest.raises(ValueError, match="not ready"):
        await service.begin_authorization()
    service.bind(SimpleNamespace(begin_authorization=lambda: "synthetic-attempt"), "channel", "bot")
    assert await service.begin_authorization() == "synthetic-attempt"


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


@pytest.mark.parametrize("live", [False, True])
async def test_stream_monitor_uses_sdk_app_login_without_bot_tokens_or_callback(monkeypatch, live):
    calls = []
    class SDKClient:
        def __init__(self, **kwargs):
            calls.append(("client", kwargs))
        async def login(self, **kwargs):
            calls.append(("login", kwargs))
        def fetch_streams(self, **kwargs):
            calls.append(("streams", kwargs))
            async def values():
                if live:
                    yield SimpleNamespace()
            return values()
        async def close(self, **kwargs):
            calls.append(("close", kwargs))
    monkeypatch.setattr("app.services.twitch.Client", SDKClient)
    service = TwitchAPIService()
    settings = Settings(_env_file=None, twitch_client_id="client", twitch_client_secret="private-sentinel",
        twitch_bot_user_id="100", twitch_bot_username="testbot", twitch_channel="channel", twitch_channel_user_id="200")
    assert await service.get_broadcaster_live(settings) is live
    assert await service.get_broadcaster_live(settings) is live
    await service.close_stream_monitor()
    await service.close_stream_monitor()
    assert [name for name, _ in calls] == ["client", "login", "streams", "streams", "close"]
    assert calls[1][1] == {"load_tokens": False, "save_tokens": False}
    assert calls[2][1] == {"user_ids": ["200"], "first": 1, "max_results": 1}
    assert calls[-1][1] == {"save_tokens": False}


async def test_failed_monitor_login_closes_client_and_allows_later_poll(monkeypatch):
    closed = []
    class SDKClient:
        def __init__(self, **kwargs):
            pass
        async def login(self, **kwargs):
            raise RuntimeError("private-provider-token")
        async def close(self, **kwargs):
            closed.append(kwargs)
    monkeypatch.setattr("app.services.twitch.Client", SDKClient)
    service = TwitchAPIService()
    settings = Settings(_env_file=None, twitch_client_id="client", twitch_client_secret="synthetic",
        twitch_bot_user_id="100", twitch_bot_username="testbot", twitch_channel="channel", twitch_channel_user_id="200")
    for _ in range(2):
        with pytest.raises(RuntimeError):
            await service.get_broadcaster_live(settings)
    assert len(closed) == 2 and service._monitor_client is None
