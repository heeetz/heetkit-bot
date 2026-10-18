"""Real TwitchIO cache format, with synthetic tokens and no HTTP requests."""

import asyncio
import json
import logging
import os
import stat
from types import SimpleNamespace

import pytest
from twitchio.exceptions import HTTPException, InvalidTokenException

from app.config.settings import Settings
from app.runtime_state import RuntimeState
from app.twitch.client import TwitchChatBot, TwitchConnectionError, run_twitch_bot


@pytest.fixture(autouse=True)
def prohibit_network(monkeypatch):
    async def forbidden(*args, **kwargs):
        pytest.fail("Network requests are forbidden in synthetic token tests")
    monkeypatch.setattr("aiohttp.ClientSession._request", forbidden)


def bot_at(tmp_path):
    value = Settings(twitch_client_id="synthetic-client", twitch_client_secret="synthetic-secret",
                     twitch_bot_user_id="100", twitch_bot_username="testbot",
                     twitch_channel_user_id="200", twitch_channel="testchannel",
                     twitch_token_file=str(tmp_path / "auth" / "tokens.json"))
    state = RuntimeState()
    return TwitchChatBot(value, value.primary_account, SimpleNamespace(twitch=None, runtime_state=state), object(), logging.getLogger(__name__))


def cache(token="old-access", refresh="old-refresh"):
    return {"100": {"user_id": "100", "token": token, "refresh": refresh, "last_validated": "2026-10-18T00:00:00"}}


@pytest.mark.asyncio
async def test_startup_rotation_final_flush_and_restart_preserve_managed_format(tmp_path, monkeypatch):
    bot = bot_at(tmp_path)
    path = bot._token_file
    path.parent.mkdir()
    original = cache() | {"200": {"token": "second-access", "refresh": "second-refresh"}}
    path.write_text(json.dumps(original), encoding="utf-8")

    async def add(token, refresh):
        identifier = "100" if token == "old-access" else "200"
        bot._http._tokens[identifier] = {"user_id": identifier, "token": "rotated-" + token, "refresh": "rotated-" + refresh, "last_validated": "2026-10-18T00:00:00"}
        # Refresh listener delivery while loading must not save half the cache.
        await bot.save_tokens()
        assert json.loads(path.read_text()) == original

    monkeypatch.setattr(bot, "add_token", add)
    await bot.load_tokens()
    assert set(json.loads(path.read_text())) == {"100", "200"}
    assert json.loads(path.read_text())["100"]["refresh"] == "rotated-old-refresh"
    bot._http._tokens["100"]["refresh"] = "final-rotation"
    await bot.close(save_tokens=False)
    assert not bot.tokens
    await bot.save_tokens()  # Simulate a queued refresh listener after close.
    assert json.loads(path.read_text())["100"]["refresh"] == "final-rotation"
    assert not list(path.parent.glob("*.tmp"))
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600

    restarted = bot_at(tmp_path)
    received = []
    async def load_again(token, refresh):
        received.append((token, refresh))
        restarted._http._tokens["100" if "old-access" in token else "200"] = {"token": token, "refresh": refresh}
    monkeypatch.setattr(restarted, "add_token", load_again)
    await restarted.load_tokens()
    assert ("rotated-old-access", "final-rotation") in received
    await restarted.close()


@pytest.mark.asyncio
async def test_failed_atomic_replace_preserves_cache_reports_failure_and_closes(tmp_path, monkeypatch, caplog):
    bot = bot_at(tmp_path)
    path = bot._token_file
    path.parent.mkdir()
    original = json.dumps(cache())
    path.write_text(original)
    bot._tokens_loaded = bot._http._has_loaded = True
    bot._http._tokens.update(cache("new-access", "new-refresh"))
    def fail(*args):
        raise OSError("private filesystem credential sentinel")
    monkeypatch.setattr("app.twitch.client.os.replace", fail)
    with pytest.raises(TwitchConnectionError):
        await bot.save_tokens()
    assert path.read_text() == original
    assert bot._services.runtime_state.twitch_connection_state == "failed"
    assert not list(path.parent.glob("*.tmp"))
    with pytest.raises(TwitchConnectionError):
        await bot.close()
    assert not bot.tokens  # Library cleanup still completed after failed final save.
    assert "private filesystem credential sentinel" not in caplog.text
    assert "new-refresh" not in caplog.text


@pytest.mark.asyncio
async def test_malformed_cache_survives_partial_startup_and_shutdown(tmp_path):
    bot = bot_at(tmp_path)
    path = bot._token_file
    path.parent.mkdir()
    path.write_text("{invalid-private-cache")
    with pytest.raises(ValueError):
        await bot.load_tokens()
    await bot.close()
    assert path.read_text() == "{invalid-private-cache"


@pytest.mark.asyncio
async def test_partial_load_failure_retains_rotation_and_unprocessed_cache(tmp_path, monkeypatch):
    bot = bot_at(tmp_path)
    path = bot._token_file
    path.parent.mkdir()
    original = cache() | {"200": {"token": "unprocessed-access", "refresh": "unprocessed-refresh"}}
    path.write_text(json.dumps(original))
    async def add(token, refresh):
        if token == "unprocessed-access":
            raise OSError("synthetic offline")
        bot._http._tokens.update(cache("rotated-access", "rotated-refresh"))
    monkeypatch.setattr(bot, "add_token", add)
    with pytest.raises(OSError):
        await bot.load_tokens()
    await bot.close()
    saved = json.loads(path.read_text())
    assert saved["100"]["refresh"] == "rotated-refresh"
    assert saved["200"] == original["200"]


@pytest.mark.asyncio
async def test_rejected_cached_token_reaches_authorization_required(tmp_path, monkeypatch):
    bot = bot_at(tmp_path)
    bot._token_file.parent.mkdir()
    bot._token_file.write_text(json.dumps(cache()))
    async def reject(*args, **kwargs):
        error = HTTPException("private", status=401, extra={})
        raise InvalidTokenException("private", token="old-access", refresh="old-refresh", type_="token", original=error)
    monkeypatch.setattr(bot, "add_token", reject)
    await bot.load_tokens()
    await bot.setup_hook()
    await bot.event_ready()
    assert bot._services.runtime_state.twitch_connection_state == "auth_required"
    await bot.close()
    assert json.loads(bot._token_file.read_text()) == cache()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["library", "removed", "listener"])
async def test_headless_disables_callback_and_surfaces_background_failure(tmp_path, monkeypatch, caplog, failure):
    bot = bot_at(tmp_path)
    services = bot._services
    services.runtime_state.set_bot_running(True)
    stop = asyncio.Event()
    started = asyncio.Event()

    async def start(**kwargs):
        assert kwargs == {"with_adapter": False, "load_tokens": True, "save_tokens": True}
        bot._http._tokens.update(cache())
        services.runtime_state.set_twitch_connection_state("connected")
        started.set()
        await stop.wait()
    monkeypatch.setattr(bot, "start", start)
    monkeypatch.setattr("app.twitch.client.TwitchChatBot", lambda **kwargs: bot)
    task = asyncio.create_task(run_twitch_bot(Settings(
        twitch_client_id="synthetic", twitch_client_secret="synthetic", twitch_bot_user_id="100", twitch_bot_username="testbot", twitch_channel="testchannel", twitch_channel_user_id="200"),
        services, object(), logging.getLogger(__name__), stop, headless=True))
    await started.wait()
    if failure == "library":
        logging.getLogger("twitchio.eventsub.websockets").error("Unable to resubscribe private token-chat sentinel", exc_info=ValueError("secret"))
    elif failure == "listener":
        await bot.event_error(SimpleNamespace(error=RuntimeError("private token-chat sentinel")))
    else:
        bot._http._tokens.clear()
        await asyncio.sleep(0.25)
    assert services.runtime_state.twitch_connection_state == ("auth_required" if failure == "removed" else "failed")
    assert "private token-chat sentinel" not in caplog.text
    stop.set()
    await task
