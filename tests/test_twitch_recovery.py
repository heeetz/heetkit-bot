"""Deterministic shared recovery failures; no credentials, live HTTP, or chat."""
import asyncio
import logging
from datetime import datetime, timedelta
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from twitchio.exceptions import HTTPException, InvalidTokenException
from twitchio.eventsub.websockets import Websocket

import app.twitch.client as lifecycle
from app.runtime_state import RuntimeState
from app.services.twitch import TwitchAPIService
from twitch_fakes import established_socket
from test_twitch_client import build_settings


async def until(predicate):
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(.001)


@pytest.fixture
def rig(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(lifecycle, "monotonic", lambda: now[0])
    monkeypatch.setattr(lifecycle, "RECOVERY_POLL", .001)
    monkeypatch.setattr(lifecycle, "CLEANUP_DEADLINE", .03)
    monkeypatch.setattr(lifecycle, "uniform", lambda a, b: 1.0)
    state = RuntimeState()
    state.set_bot_running(True)
    clients = []
    outcomes = []
    stop = asyncio.Event()

    class Client:
        def __init__(self, **kwargs):
            assert all(c.closed for c in clients), "Replacement overlapped retired command owner"
            self._services = kwargs["services"]
            self._retired = False
            self._had_authorization = False
            self._lifecycle_error = None
            self.usable = False
            self.closed = False
            self.started = asyncio.Event()
            self.options = None
            clients.append(self)

        async def start(self, **kwargs):
            self.options = kwargs
            self.started.set()
            if outcomes:
                result = outcomes.pop(0)
                if result is not None:
                    raise result
            await asyncio.Event().wait()

        def refresh_readiness(self):
            if self.usable:
                state.set_twitch_connection_state("connected")
                self._had_authorization = True
            return self.usable

        async def close(self, **kwargs):
            self.closed = True

    monkeypatch.setattr(lifecycle, "TwitchChatBot", Client)
    services = NS(runtime_state=state)
    def run(headless=False):
        return asyncio.create_task(lifecycle.run_twitch_bot(build_settings(), services, object(),
            logging.getLogger("tests.recovery"), stop, headless=headless))
    return NS(now=now, state=state, clients=clients, outcomes=outcomes, stop=stop, run=run)


@pytest.mark.parametrize("headless", [False, True])
async def test_stalled_sdk_recovery_retires_then_recovers_repeatedly(rig, headless):
    r = rig
    task = r.run(headless)
    try:
        await until(lambda: len(r.clients) == 1)
        # No close event or exception: SDK start remains alive but makes no progress.
        assert r.state.twitch_recovery["reason"] == "startup"
        for cycle in range(3):
            current = r.clients[-1]
            await until(current.started.is_set)
            current.usable = True
            await until(lambda: r.state.twitch_connected)
            assert r.state.twitch_recovery is None
            current.usable = False
            r.now[0] += 1
            await until(lambda: r.state.twitch_recovery is not None)
            r.now[0] += 121
            await until(lambda: (r.state.twitch_recovery or {}).get("reason") == "retry_wait")
            assert current.closed and not task.done()
            assert r.state.twitch_recovery["next_retry_seconds"] == 5 * 2 ** cycle
            r.now[0] += 121
            await until(lambda: len(r.clients) == cycle + 2)
        r.clients[-1].usable = True
        await until(lambda: r.state.twitch_connected)
        assert all(c.options["with_adapter"] is (not headless) for c in r.clients)
    finally:
        r.stop.set()
        await task
    assert all(c.closed for c in r.clients)
    assert r.state.twitch_recovery is None


@pytest.mark.parametrize("headless", [False, True])
@pytest.mark.parametrize("failure", [OSError("PRIVATE"), HTTPException("PRIVATE", status=503, extra={}),
    HTTPException("PRIVATE", status=429, extra={}),
    InvalidTokenException("PRIVATE", token="TOKEN", refresh="REFRESH", type_="token",
        original=HTTPException("PRIVATE", status=500, extra={}))])
async def test_initial_network_or_service_failure_restores_without_losing_intent(rig, headless, failure, caplog):
    r = rig
    r.outcomes.append(failure)
    task = r.run(headless)
    try:
        await until(lambda: (r.state.twitch_recovery or {}).get("reason") == "retry_wait")
        delay = r.state.twitch_recovery["next_retry_seconds"]
        assert delay == (120 if failure.status == 429 else 5) if isinstance(failure, HTTPException) else delay == 5
        assert not task.done() and r.state.status()[0]
        r.now[0] += 121
        await until(lambda: len(r.clients) == 2)
        r.clients[-1].usable = True
        await until(lambda: r.state.twitch_connected)
    finally:
        r.stop.set()
        await task
    assert not any(secret in caplog.text for secret in ("PRIVATE", "TOKEN", "REFRESH"))


async def test_startup_without_any_welcome_is_bounded(rig):
    r = rig
    task = r.run()
    await until(lambda: len(r.clients) == 1)
    r.now[0] = 121
    await until(lambda: (r.state.twitch_recovery or {}).get("reason") == "retry_wait")
    assert r.clients[0].closed and not task.done()
    r.stop.set()
    await task
    r.now[0] += 10000
    await asyncio.sleep(.005)
    assert len(r.clients) == 1


@pytest.mark.parametrize("status", [400, 401, 403, 404])
async def test_terminal_lifecycle_access_failure_does_not_retry(rig, status):
    r = rig
    r.outcomes.append(HTTPException("private authorization", status=status, extra={}))
    with pytest.raises(lifecycle.TwitchConnectionError):
        await r.run()
    assert r.state.twitch_connection_state == ("auth_required" if status == 401 else "failed")
    assert len(r.clients) == 1 and r.clients[0].closed
    assert r.state.twitch_recovery is None


async def test_cleanup_timeout_blocks_replacement(rig, monkeypatch):
    r = rig
    r.outcomes.append(OSError("offline"))
    release = asyncio.Event()
    original = lifecycle.TwitchChatBot.close
    async def close(self, **kwargs):
        await release.wait()
        await original(self, **kwargs)
    monkeypatch.setattr(lifecycle.TwitchChatBot, "close", close)
    task = r.run()
    try:
        with pytest.raises(lifecycle.TwitchCleanupError):
            await task
        assert len(r.clients) == 1 and r.clients[0]._retired
        assert r.state.twitch_connection_state == "failed"
    finally:
        release.set()


@pytest.fixture
def real_bot():
    settings = build_settings()
    state = RuntimeState()
    state.set_bot_running(True)
    services = NS(runtime_state=state, twitch=TwitchAPIService())
    bot = lifecycle.TwitchChatBot(settings, settings.primary_account, services, object(), logging.getLogger("tests.real.recovery"))
    bot._http._tokens[bot.bot_id] = {}
    return bot


async def test_welcome_waits_for_subscriptions_and_send_authorization(real_bot):
    bot = real_bot
    state = bot._services.runtime_state
    socket = established_socket(bot)
    socket._connecting = True
    socket._subscriptions.clear()
    try:
        await bot.event_websocket_welcome(NS(id=socket.session_id))
        assert not state.twitch_connected and not bot._services.twitch.chat_connected
        socket._connecting = False
        assert not bot.refresh_readiness()
        socket._subscriptions["chat"] = {"type": "channel.chat.message", "condition": {
            "broadcaster_user_id": "200", "user_id": "100"}}
        assert bot.refresh_readiness() and bot._services.twitch.chat_connected
        bot._send_authorized = False
        assert not bot.refresh_readiness() and not bot._services.twitch.chat_connected
        assert state.twitch_connection_state == "auth_required"
    finally:
        await bot.close()


async def test_protocol_keepalives_allow_quiet_channel_and_detect_dead_reader(real_bot):
    bot = real_bot
    socket = established_socket(bot)
    try:
        for _ in range(5):
            socket._last_keepalive = datetime.now()  # No chat messages at all.
            assert bot.refresh_readiness()
        socket._last_keepalive = datetime.now() - timedelta(seconds=100)
        assert not bot.refresh_readiness()
        assert bot._services.runtime_state.twitch_connection_state == "reconnecting"
    finally:
        await bot.close()


async def test_sdk_reused_socket_close_keeps_its_dispatch_time_identity(real_bot):
    bot = real_bot
    socket = established_socket(bot, "old")
    bot._active_socket_id = "old"
    bot.refresh_readiness()
    # The async close callback holds the same mutable object that will receive
    # welcome. Dispatch both before letting either handler run.
    bot.dispatch("websocket_closed", NS(socket=socket))
    socket._session_id = "new"
    bot.dispatch("websocket_welcome", NS(id="new"))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert bot._services.runtime_state.twitch_connected
    assert bot._services.twitch.chat_connected
    await bot.close()


async def test_retired_callbacks_cannot_invalidate_new_owner(real_bot):
    old = real_bot
    socket = established_socket(old, "old")
    old.refresh_readiness()
    new = lifecycle.TwitchChatBot(old._settings, old._account, old._services, object(), logging.getLogger("tests.real.recovery"))
    new._http._tokens["100"] = {}
    established_socket(new, "new")
    try:
        assert new.refresh_readiness()
        await old.event_websocket_closed(NS(socket=socket))
        await old.event_subscription_revoked(NS(type="channel.chat.message", status=NS(value="authorization_revoked")))
        await old.event_websocket_welcome(NS(id="old"))
        assert new._services.runtime_state.twitch_connected and new._services.twitch.chat_connected
    finally:
        await old.close()
        await new.close()


async def test_retirement_drains_command_owner_before_releasing_client(real_bot):
    bot = real_bot
    entered, canceled = asyncio.Event(), asyncio.Event()
    async def handler(message):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            canceled.set()
    bot._handle_message = handler
    pending = asyncio.create_task(bot.event_message(object()))
    await entered.wait()
    await bot.close()
    assert pending.cancelled() and canceled.is_set()
    assert bot._services.twitch._client is None


async def test_old_socket_ingress_does_not_reserve_replacement_replay_id(real_bot):
    from app.twitch.client import _transport_origin
    bot = real_bot
    established_socket(bot, "new")
    bot.refresh_readiness()
    calls = []
    async def process(**kwargs):
        calls.append(kwargs["message"].id)
    original = lifecycle.process_twitch_message
    lifecycle.process_twitch_message = process
    message = NS(id="once", broadcaster=NS(id="200", name="testchannel"))
    try:
        token = _transport_origin.set(bot._socket_ref("old"))
        try:
            await bot.event_message(message)
        finally:
            _transport_origin.reset(token)
        await bot.event_message(message)
        await bot.event_message(message)
        assert calls == ["once"]
    finally:
        lifecycle.process_twitch_message = original
        await bot.close()


async def test_oauth_in_flight_finishes_rotation_before_cleanup_and_cannot_subscribe(real_bot, tmp_path, monkeypatch):
    import json
    bot = real_bot
    entered, release = asyncio.Event(), asyncio.Event()
    bot._token_file = tmp_path / "synthetic.json"
    async def add(*args):
        entered.set()
        await release.wait()
        bot._http._tokens["100"] = {"token": "synthetic-rotation", "refresh": "synthetic-refresh"}
        return NS(user_id="100", scopes=["user:write:chat"])
    monkeypatch.setattr(bot, "add_token", add)
    subscribe = AsyncMock()
    monkeypatch.setattr(bot, "_subscribe_to_chat", subscribe)
    bot.dispatch("oauth_authorized", {"access_token": "synthetic", "refresh_token": "synthetic"})
    await entered.wait()
    closing = asyncio.create_task(bot.close())
    await asyncio.sleep(0)
    assert not closing.done()
    release.set()
    await closing
    subscribe.assert_not_awaited()
    assert json.loads(bot._token_file.read_text())["100"]["token"] == "synthetic-rotation"
    assert not bot.tokens


async def test_start_finally_save_failure_cannot_be_hidden_by_second_close(real_bot, tmp_path, monkeypatch):
    bot = real_bot
    bot._tokens_loaded = True
    bot._token_file = tmp_path / "synthetic.json"
    def fail(*args):
        raise OSError("private path")
    monkeypatch.setattr(lifecycle.os, "replace", fail)
    entered = asyncio.Event()
    async def start():
        try:
            entered.set()
            await asyncio.Event().wait()
        finally:
            await bot.close()
    task = asyncio.create_task(start())
    await entered.wait()
    loop = asyncio.get_running_loop()
    previous = loop.get_exception_handler()
    unhandled = []
    loop.set_exception_handler(lambda loop, context: unhandled.append(context))
    try:
        with pytest.raises(lifecycle.TwitchCleanupError):
            await lifecycle._retire_client(bot, task, logging.getLogger("tests.cleanup"))
        with pytest.raises(lifecycle.TwitchCleanupError):
            await bot.close()
        import gc
        gc.collect()
        await asyncio.sleep(0)
        assert not unhandled
    finally:
        loop.set_exception_handler(previous)


async def test_server_migration_preserves_url_subscription_transfer_and_welcome_before_close(real_bot, monkeypatch):
    from app.twitch.socket import OwnedWebsocket
    bot = real_bot
    old = OwnedWebsocket(client=bot, token_for="100", http=bot._http)
    old._session_id = "old"
    old._socket = NS(closed=False, close=AsyncMock())
    old._subscriptions["chat"] = {"type": "channel.chat.message"}
    bot._websockets["100"] = {"old": old}
    welcomed, release = asyncio.Event(), asyncio.Event()
    candidates = []
    url = "wss://synthetic.invalid/?opaque=migration&keep=unchanged"
    async def connect(self, **kwargs):
        candidates.append(self)
        assert kwargs == {"url": url, "reconnect": False, "fail_once": True}
        assert self._subscriptions is old._subscriptions
        assert old._socket.close.await_count == 0
        self._session_id = "new"
        self._socket = NS(closed=False, close=AsyncMock())
        welcomed.set()
        await release.wait()
    monkeypatch.setattr(OwnedWebsocket, "connect", connect)
    subscription_api = AsyncMock(side_effect=AssertionError("Migration must not recreate subscriptions"))
    monkeypatch.setattr(bot._http, "create_eventsub_subscription", subscription_api)
    handover = asyncio.create_task(old._reconnect(url))
    await welcomed.wait()
    assert not old._closed
    release.set()
    await handover
    assert old._closed and bot._websockets["100"] == {"new": candidates[0]}
    subscription_api.assert_not_awaited()
    await bot.close()


async def test_canceled_migration_candidate_is_owned_until_cleanup(real_bot, monkeypatch):
    from app.twitch.socket import OwnedWebsocket
    bot = real_bot
    old = OwnedWebsocket(client=bot, token_for="100", http=bot._http)
    old._session_id = "old"
    bot._websockets["100"] = {"old": old}
    entered = asyncio.Event()
    async def connect(self, **kwargs):
        self._socket = NS(closed=False, close=AsyncMock())
        entered.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(OwnedWebsocket, "connect", connect)
    handover = asyncio.create_task(old._reconnect("wss://synthetic.invalid"))
    await entered.wait()
    candidates = bot._owned_sockets - {old}
    assert len(candidates) == 1
    handover.cancel()
    await asyncio.gather(handover, return_exceptions=True)
    await bot.close()
    assert not bot._owned_sockets
    assert all(socket._closed for socket in candidates)


@pytest.mark.parametrize("headless", [False, True])
async def test_runtime_latches_cleanup_failure_even_when_stop_was_requested(monkeypatch, headless):
    from app.bot_runtime import BotRuntime
    from test_bot_runtime import FakeApplication
    app = FakeApplication()
    ready = asyncio.Event()
    async def session(**kwargs):
        ready.set()
        await kwargs["stop_event"].wait()
        app.services.runtime_state.set_twitch_connection_state("failed")
        raise lifecycle.TwitchCleanupError("unsafe cleanup")
    monkeypatch.setattr("app.bot_runtime.run_twitch_bot", session)
    runtime = BotRuntime(app, logging.getLogger("tests.runtime.cleanup"), headless=headless)
    await runtime.startup()
    await runtime.start_bot()
    await ready.wait()
    try:
        try:
            await runtime.stop_bot()
        except lifecycle.TwitchCleanupError:
            pass
        assert app.services.runtime_state.twitch_connection_state == "failed"
        with pytest.raises(lifecycle.TwitchCleanupError):
            await runtime.start_bot()
    finally:
        try:
            await runtime.shutdown()
        except lifecycle.TwitchCleanupError:
            pass


async def test_welcome_alone_cannot_restore_connected(real_bot):
    bot = real_bot
    socket = established_socket(bot, "candidate")
    socket._connecting = True
    socket._subscriptions.clear()
    bot._services.runtime_state.set_twitch_connection_state("reconnecting")
    try:
        await bot.event_websocket_welcome(NS(id="candidate"))
        assert not bot._services.runtime_state.twitch_connected
        assert not bot._services.twitch.chat_connected
    finally:
        await bot.close()


async def test_delayed_sdk_close_cannot_read_the_reused_sockets_new_id(real_bot, monkeypatch):
    bot = real_bot
    socket = established_socket(bot, "old")
    await bot.event_websocket_welcome(NS(id="old"))
    await bot.event_ready()
    entered, release = asyncio.Event(), asyncio.Event()
    dispatch = bot._dispatch
    async def delayed(listener, *, original=None):
        if getattr(listener, "__name__", "") == "event_websocket_closed":
            entered.set()
            await release.wait()
        await dispatch(listener, original=original)
    monkeypatch.setattr(bot, "_dispatch", delayed)
    bot.dispatch("websocket_closed", NS(socket=socket))
    await entered.wait()
    socket._session_id = "new"
    await bot.event_websocket_welcome(NS(id="new"))
    release.set()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    try:
        assert bot._services.runtime_state.twitch_connected
        assert bot._services.twitch.chat_connected
    finally:
        await bot.close()


async def test_prolonged_outage_caps_backoff_and_stop_interrupts_wait(rig):
    r = rig
    r.outcomes.extend([OSError("offline") for _ in range(8)])
    task = r.run()
    try:
        for attempt, expected in enumerate([5, 10, 20, 40, 80, 120, 120, 120], 1):
            await until(lambda: len(r.clients) == attempt and (r.state.twitch_recovery or {}).get("reason") == "retry_wait")
            assert r.state.twitch_recovery["next_retry_seconds"] == expected
            assert not task.done()
            if attempt < 8:
                r.now[0] += 121
    finally:
        r.stop.set()
        await task
    assert len(r.clients) == 8


@pytest.mark.parametrize("status", [401, 503])
async def test_sdk_swallowed_resubscription_http_failure_reaches_supervisor(rig, status):
    r = rig
    task = r.run()
    try:
        await until(lambda: len(r.clients) == 1)
        socket = Websocket(client=None, token_for="100", http=NS(create_eventsub_subscription=AsyncMock(
            side_effect=HTTPException("PRIVATE", status=status, extra={}))))
        socket._session_id = "replacement"
        socket._subscriptions["old"] = {"type": "channel.chat.message", "transport": {}}
        # Real SDK catches and only logs this exception instead of propagating it.
        await socket._resubscribe()
        if status == 401:
            with pytest.raises(lifecycle.TwitchConnectionError):
                await task
            assert r.state.twitch_connection_state == "auth_required"
        else:
            await until(lambda: (r.state.twitch_recovery or {}).get("reason") == "retry_wait")
            assert not task.done()
    finally:
        r.stop.set()
        if not task.done():
            await task


async def test_sdk_reconnect_task_error_is_consumed_and_forwarded(real_bot, monkeypatch):
    from app.twitch.socket import OwnedWebsocket
    from twitchio.exceptions import WebsocketConnectionException
    bot = real_bot
    socket = OwnedWebsocket(client=bot, token_for="100", http=bot._http)
    error = WebsocketConnectionException("synthetic welcome timeout")
    async def connect(self, **kwargs):
        raise error
    monkeypatch.setattr(OwnedWebsocket, "connect", connect)
    loop = asyncio.get_running_loop()
    previous = loop.get_exception_handler()
    unhandled = []
    loop.set_exception_handler(lambda loop, context: unhandled.append(context))
    try:
        await socket._create_connection_task()
        await until(lambda: bot._lifecycle_error is error)
        assert not unhandled
    finally:
        await bot.close()
        loop.set_exception_handler(previous)


@pytest.mark.parametrize("error", [PermissionError(13, "private storage", "private-path"),
    OSError(28, "private storage"), HTTPException("private", status=403, extra={})])
async def test_storage_or_lifecycle_access_errors_are_terminal(rig, error):
    r = rig
    r.outcomes.append(error)
    with pytest.raises(lifecycle.TwitchConnectionError):
        await r.run()
    assert r.state.twitch_connection_state == "failed"
    assert len(r.clients) == 1


async def test_desktop_oauth_can_leave_actionable_auth_state(real_bot, tmp_path, monkeypatch):
    bot = real_bot
    bot._token_file = tmp_path / "synthetic.json"
    bot._services.runtime_state.set_twitch_connection_state("auth_required")
    async def add(*args):
        bot._http._tokens["100"] = {"token": "synthetic", "refresh": "synthetic"}
        return NS(user_id="100", scopes=["user:write:chat"])
    async def subscribe():
        established_socket(bot)
    monkeypatch.setattr(bot, "add_token", add)
    monkeypatch.setattr(bot, "_subscribe_to_chat", subscribe)
    try:
        await bot.event_oauth_authorized({"access_token": "synthetic", "refresh_token": "synthetic"})
        assert bot._services.runtime_state.twitch_connected
        assert bot._services.twitch.chat_connected
    finally:
        await bot.close()


async def test_desktop_oauth_renewal_keeps_healthy_subscription(real_bot, tmp_path, monkeypatch):
    bot = real_bot
    established_socket(bot)
    bot.refresh_readiness()
    original = bot._services.twitch.chat_session(bot)
    bot._token_file = tmp_path / "synthetic.json"
    async def add(*args):
        bot._http._tokens["100"] = {"token": "synthetic", "refresh": "synthetic"}
        return NS(user_id="100", scopes=["user:write:chat"])
    subscribe = AsyncMock()
    monkeypatch.setattr(bot, "add_token", add)
    monkeypatch.setattr(bot, "_subscribe_to_chat", subscribe)
    try:
        await bot.event_oauth_authorized({"access_token": "synthetic", "refresh_token": "synthetic"})
        subscribe.assert_not_awaited()
        assert bot._services.twitch.chat_session(bot) is original and original.active
    finally:
        await bot.close()


@pytest.mark.parametrize("headless", [False, True])
async def test_runtime_fresh_recovery_recreates_real_sdk_subscription(tmp_path, monkeypatch, headless):
    from app.bot_runtime import BotRuntime
    from app.twitch.socket import OwnedWebsocket
    from test_bot_runtime import FakeApplication
    now = [0.0]
    monkeypatch.setattr(lifecycle, "monotonic", lambda: now[0])
    monkeypatch.setattr(lifecycle, "RECOVERY_POLL", .001)
    monkeypatch.setattr(lifecycle, "uniform", lambda a, b: 1.0)
    clients, subscriptions = [], []
    app = FakeApplication()
    app.settings = build_settings()
    app.settings.twitch_token_file = str(tmp_path / "unused.json")
    app.services = NS(twitch=TwitchAPIService(), runtime_state=RuntimeState())
    async def connect(socket, **kwargs):
        socket._session_id = "synthetic-" + str(len(subscriptions))
        socket._socket = NS(closed=False, close=AsyncMock())
        socket._listen_task = asyncio.create_task(asyncio.Event().wait())
        socket._last_keepalive = datetime.now()
        socket._ready.set()
    async def start(bot, **kwargs):
        assert kwargs["with_adapter"] is (not headless)
        bot._http._tokens["100"] = {}
        bot._send_authorized = True
        async def subscribe(**data):
            subscriptions.append(data)
            return {"data": [{"id": "sub-" + str(len(subscriptions))}]}
        bot._http.create_eventsub_subscription = subscribe
        await bot.setup_hook()  # Application + real SDK subscribe_websocket.
        await bot.event_ready()
        clients.append(bot)
        await asyncio.Event().wait()
    monkeypatch.setattr(OwnedWebsocket, "connect", connect)
    monkeypatch.setattr(lifecycle.TwitchChatBot, "start", start)
    runtime = BotRuntime(app, logging.getLogger("tests.runtime.real"), headless=headless)
    await runtime.startup()
    await runtime.start_bot()
    try:
        await until(lambda: len(clients) == 1 and app.services.runtime_state.twitch_connected)
        old = clients[0]
        for socket in old._registered_sockets():
            socket._last_keepalive -= timedelta(seconds=100)
        await until(lambda: app.services.runtime_state.twitch_recovery is not None)
        now[0] += 121
        await until(lambda: (app.services.runtime_state.twitch_recovery or {}).get("reason") == "retry_wait")
        now[0] += 121
        await until(lambda: len(clients) == 2 and app.services.runtime_state.twitch_connected)
        assert old._closing_requested and not old._ingress_tasks
        assert len(subscriptions) == 2
        assert subscriptions[0]["transport"]["session_id"] != subscriptions[1]["transport"]["session_id"]
        assert all(sub["condition"] == {"broadcaster_user_id": "200", "user_id": "100"} for sub in subscriptions)
    finally:
        await runtime.shutdown()
    assert not runtime.bot_active and app.services.twitch._client is None


@pytest.mark.parametrize("action", ["stop", "shutdown", "channel"])
async def test_shared_backoff_serializes_with_runtime_lifecycle(rig, action):
    from app.bot_runtime import BotRuntime
    from test_bot_runtime import FakeApplication
    r = rig
    app = FakeApplication()
    app.settings = build_settings()
    app.services = NS(runtime_state=r.state)
    runtime = BotRuntime(app, logging.getLogger("tests.runtime.backoff"))
    await runtime.startup()
    r.outcomes.append(OSError("offline"))
    await runtime.start_bot()
    await until(lambda: (r.state.twitch_recovery or {}).get("reason") == "retry_wait")
    try:
        if action == "channel":
            assert await runtime.reconnect_twitch(channel="newchannel", channel_user_id="300")
            await until(lambda: len(r.clients) == 2)
            r.clients[-1].usable = True
            await until(lambda: r.state.twitch_connected)
            assert app.settings.twitch_channel == "newchannel"
        elif action == "stop":
            assert await runtime.stop_bot()
        else:
            await runtime.shutdown()
        if action != "channel":
            r.now[0] += 10000
            await asyncio.sleep(.005)
            assert len(r.clients) == 1 and not runtime.bot_active
    finally:
        await runtime.shutdown()


async def test_handover_ingress_is_accepted_before_old_close_completes(real_bot, monkeypatch):
    from app.twitch.client import _transport_origin
    bot = real_bot
    old = established_socket(bot, "old")
    bot.refresh_readiness()
    new = established_socket(bot, "new")
    bot._websockets["100"]["old"] = old  # Both are owned during handover.
    new._connecting = True
    processed = []
    async def process(**kwargs):
        processed.append(kwargs["message"].id)
    monkeypatch.setattr(lifecycle, "process_twitch_message", process)
    token = _transport_origin.set(bot._socket_ref("new"))
    try:
        await bot.event_message(NS(id="handover", broadcaster=NS(id="200", name="testchannel")))
        assert processed == ["handover"]
    finally:
        _transport_origin.reset(token)
        await bot.close()


async def test_websocket_handshake_rate_limit_honors_retained_retry_header(rig):
    from aiohttp import ClientResponseError
    from twitchio.exceptions import WebsocketConnectionException
    r = rig
    error = WebsocketConnectionException("private")
    error.__cause__ = ClientResponseError(None, (), status=429, headers={"Retry-After": "600"})
    r.outcomes.append(error)
    task = r.run()
    try:
        await until(lambda: (r.state.twitch_recovery or {}).get("reason") == "retry_wait")
        assert r.state.twitch_recovery["next_retry_seconds"] == 600
        assert r.state.twitch_recovery["cause"] == "rate_limited"
    finally:
        r.stop.set()
        await task
