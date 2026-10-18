"""Private HTTP integration against synthetic profiles and the real shared core."""

import asyncio
import json
import logging
import socket

import aiohttp
import pytest

from app import headless
from app.app_settings import AppSettings, AppSettingsStore
from app.bot_runtime import BotRuntime
from app.config.profile_settings import apply_ai_app_settings
from app.config.settings import Settings
from app.container import build_application
from app.management_api import ManagementAPI, ManagementConfig, load_management_token
from app.runtime_paths import RuntimePaths, prepare_runtime_data
from app.utils.logging import RecentLogBuffer


TOKEN = "synthetic_management_token_" + "x" * 32


@pytest.fixture(autouse=True)
def private_profile(tmp_path, monkeypatch):
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    for name in ("HEETKIT_MANAGEMENT_TOKEN", "HEETKIT_MANAGEMENT_TOKEN_FILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HEETKIT_DATA_DIR", str(tmp_path / "profile"))
    async def no_network(*args, **kwargs):
        raise AssertionError("External network is forbidden in management tests")
    monkeypatch.setattr("httpx.AsyncClient.send", no_network)
    async def no_lookup(*args):
        return None
    monkeypatch.setattr("app.services.twitch.TwitchAPIService.resolve_user_id", no_lookup)


def settings():
    paths = RuntimePaths.default()
    value = Settings(twitch_client_id="synthetic-client", twitch_client_secret="private-client-sentinel",
        twitch_bot_username="syntheticbot", twitch_bot_user_id="100",
        twitch_channel="syntheticchannel", twitch_channel_user_id="200",
        twitch_token_file=str(paths.tokens), database_url="sqlite+aiosqlite:///" + str(paths.database))
    prepare_runtime_data(value.twitch_token_file, value.database_url)
    return value


@pytest.fixture
async def api(unused_tcp_port):
    app = build_application(settings())
    runtime = BotRuntime(app, logging.getLogger("test"), headless=True)
    await runtime.startup()
    server = ManagementAPI(runtime, ManagementConfig(TOKEN, port=unused_tcp_port), RecentLogBuffer())
    await server.start()
    async with aiohttp.ClientSession(headers={"Authorization": "Bearer " + TOKEN}, trust_env=False) as client:
        async def call(method, path, **kwargs):
            async with client.request(method, f"http://127.0.0.1:{unused_tcp_port}" + path, **kwargs) as response:
                return response.status, await response.json(), response.headers
        yield server, call
    await server.close()
    await runtime.shutdown()


@pytest.mark.asyncio
async def test_authentication_origin_host_and_private_surface(api):
    server, call = api
    for headers, expected in [
        ({"Authorization": ""}, 401),
        ({"Authorization": "Bearer wrong"}, 401),
        ({"Origin": "http://evil.test"}, 403),
        ({"Origin": "null"}, 403),
        ({"Cookie": "session=anything"}, 403),
        ({"Sec-Fetch-Site": "cross-site"}, 403),
        ({"Host": "evil.test"}, 403),
    ]:
        status, body, _ = await call("GET", "/v1/status", headers=headers)
        assert status == expected
        assert TOKEN not in json.dumps(body)
    status, body, headers = await call("GET", "/v1/status")
    assert status == 200 and body["account"] == "syntheticbot"
    assert headers["Cache-Control"] == "no-store"
    assert "Access-Control-Allow-Origin" not in headers
    for path in ("/v1/get_credentials", "/v1/_backend", "/v1/open_profile_folder", "/v1/replace_credential"):
        assert (await call("POST", path, json={}))[0] == 404
    assert (await call("OPTIONS", "/v1/status"))[0] == 405
    assert (await call("GET", "/v1/status?token=secret"))[0] == 400
    for path in ("/v1/ai/models", "/v1/diagnostics"):
        _, body, _ = await call("GET", path)
        assert "private-client-sentinel" not in json.dumps(body)
        assert TOKEN not in json.dumps(body)


@pytest.mark.asyncio
async def test_strict_bounded_json_and_no_partial_mutation(api):
    server, call = api
    for raw in ('{"enabled":true,"enabled":false}', '{"enabled":NaN}', '[]', '{ ',
                '{"enabled":true,"secret":"private-sentinel"}', '{"enabled":"yes"}'):
        status, body, _ = await call("POST", "/v1/ai/enabled", data=raw,
            headers={"Content-Type": "application/json"})
        assert status == 400
        assert "private-sentinel" not in json.dumps(body)
    assert (await call("POST", "/v1/ai/enabled", data="{}"))[0] == 415
    assert (await call("POST", "/v1/ai/enabled", data=b"x" * 65537,
        headers={"Content-Type": "application/json"}))[0] == 413
    assert (await call("POST", "/v1/ai/enabled", json={}, headers={"Content-Encoding": "gzip"}))[0] == 400
    before = server.service.get_commands()
    result = await call("POST", "/v1/commands/save", json={"command_name": "erase", "enabled": True,
        "per_user_seconds": 0, "global_seconds": 0, "permission": "USER"})
    assert result[0] == 400  # immutable administrative permission floor
    assert server.service.get_commands() == before


@pytest.mark.asyncio
async def test_management_applies_and_persists_existing_stores(api):
    server, call = api
    async def save(path, payload):
        status, body, _ = await call("POST", path, json=payload)
        assert status == 200, body
        assert body.get("ok", True)
        return body
    await save("/v1/commands/save", {"command_name": "ping", "enabled": False,
        "per_user_seconds": 7, "global_seconds": 3, "permission": "MODERATOR",
        "options": {"aliases": ["latency"], "display_name": "Latency"}})
    await save("/v1/commands/responses/save", {"name": "fate", "responses": ["Synthetic fate"]})
    custom = {"name": "greeting", "enabled": True, "responses": ["Hi {sender}"], "permission": "USER",
              "per_user_seconds": 4, "global_seconds": 2, "aliases": ["salute"]}
    await save("/v1/custom-commands/save", {"command": custom})
    await save("/v1/ai/enabled", {"enabled": False})
    await save("/v1/ai/memory", {"enabled": False})
    await save("/v1/ai/models", {"selected_model": "gemini-synthetic-a", "fallback_model": "gemini-synthetic-b"})
    await save("/v1/ai/language", {"mode": "limited", "allowed_languages": ["en"], "fallback_language": "en"})
    await save("/v1/personalities/create", {"name": "Synthetic", "prompt": "Synthetic prompt"})
    await save("/v1/personalities/save", {"personality": "Synthetic", "prompt": "Edited prompt"})
    await save("/v1/personalities/activate", {"personality": "Synthetic"})
    await save("/v1/ai/instructions/save", {"prompt": "Synthetic instructions"})
    await save("/v1/filters/save", {"payload": {"words": ["syntheticblocked"], "phrases": [], "patterns": []}})
    result = await save("/v1/filters/test", {"text": "syntheticblocked", "source": "active", "payload": None})
    assert result["decision"] == "BLOCK"
    await save("/v1/blocked-users/block", {"username": "syntheticviewer"})
    trigger = {"id": "hello", "enabled": True, "match_mode": "exact", "text": "hello",
               "case_sensitive": False, "probability": 1, "cooldown_seconds": 10, "responses": ["Hi"]}
    await save("/v1/triggers", {"triggers": [trigger]})
    assert server.runtime.application.services.runtime_state.active_ai_personality == "Synthetic"
    assert not server.runtime.application.services.runtime_state.ai_memory_enabled
    assert server.runtime.application.dispatcher._message_triggers.list()[0].matches("HELLO")
    # Load a second composition only after inspecting persisted settings. No live
    # account, private profile, desktop host or second Twitch session is involved.
    profile = AppSettingsStore(RuntimePaths.default().app_settings).snapshot()
    clone = build_application(apply_ai_app_settings(settings(), profile))
    await clone.startup()
    try:
        state = clone.services.runtime_state
        command = state.get_command_settings("ping")
        assert not command.enabled and command.aliases == ("latency",)
        assert command.permission.name == "MODERATOR" and command.cooldown.per_user_seconds == 7
        assert not state.ai_enabled and not profile.ai.memory_enabled
        assert clone.settings.gemini_model == "gemini-synthetic-a"
        assert state.active_ai_personality == "Synthetic"
        assert clone.custom_commands.get_by_name("salute").responses == ("Hi {sender}",)
        assert clone.fun_settings.snapshot("fate")["responses"] == ["Synthetic fate"]
        assert not clone.services.filter_manager.filter_message("syntheticblocked")
        assert clone.services.ai_user_blocks.is_blocked("", "syntheticviewer")
        assert clone.dispatcher._message_triggers.list()[0].id == "hello"
    finally:
        await clone.shutdown()


@pytest.mark.asyncio
async def test_serialized_updates_failures_limits_and_safe_logs(api, monkeypatch):
    server, call = api
    replies = await asyncio.gather(*[call("POST", "/v1/ai/memory", json={"enabled": bool(n % 2)}) for n in range(8)])
    assert all(reply[0] == 200 for reply in replies)
    persisted = AppSettingsStore(RuntimePaths.default().app_settings).snapshot().ai.memory_enabled
    assert persisted == server.runtime.application.services.runtime_state.ai_memory_enabled
    record = logging.LogRecord("test", logging.ERROR, "", 0, "private-token-sentinel", (), None)
    record.event_kind = "twitch.connected"
    server.log_buffer.append(record, "private-token-sentinel")
    _, body, _ = await call("POST", "/v1/logs/recent", json={})
    assert body["entries"][0]["message"] == "Twitch lifecycle: twitch.connected"
    assert "private-token-sentinel" not in json.dumps(body)
    def fail(*args, **kwargs):
        raise OSError("private-path-secret-sentinel")
    monkeypatch.setattr(server.service._app_settings, "update_ai_memory", fail)
    status, body, _ = await call("POST", "/v1/ai/memory", json={"enabled": not persisted})
    assert status == 500 and "private-path-secret-sentinel" not in json.dumps(body)
    assert persisted == server.runtime.application.services.runtime_state.ai_memory_enabled
    server.requests.extend([asyncio.get_running_loop().time()] * 120)
    assert (await call("GET", "/v1/status"))[0] == 429


@pytest.mark.asyncio
async def test_partial_connections_headers_and_operation_deadlines_are_bounded(api, monkeypatch):
    server, call = api
    monkeypatch.setattr("app.management_api.CONNECTION_SECONDS", 0.1)
    reader, writer = await asyncio.open_connection("127.0.0.1", server.config.port)
    try:
        writer.write(b"GET /v1/status HTTP/1.1\r\nHost:")
        await writer.drain()
        assert await asyncio.wait_for(reader.read(), 1) == b""
    finally:
        writer.close()
        await writer.wait_closed()
    monkeypatch.setattr("app.management_api.CONNECTION_SECONDS", 35)
    connections = []
    try:
        for _ in range(33):
            connections.append(await asyncio.open_connection("127.0.0.1", server.config.port))
        assert await asyncio.wait_for(connections[-1][0].read(), 1) == b""
    finally:
        for _, connection in connections:
            connection.close()
        await asyncio.gather(*(connection.wait_closed() for _, connection in connections))
    reader, writer = await asyncio.open_connection("127.0.0.1", server.config.port)
    try:
        writer.write(b"GET /v1/status HTTP/1.1\r\nHost: " + b"x" * 3000 + b"\r\n\r\n")
        await writer.drain()
        assert b"400" in await asyncio.wait_for(reader.read(), 1)
    finally:
        writer.close()
        await writer.wait_closed()
    async def slow_operation(enabled):
        await asyncio.sleep(10)
    monkeypatch.setattr(server.service, "_save_ai_memory_enabled", slow_operation)
    monkeypatch.setattr("app.management_api.REQUEST_SECONDS", 0.05)
    assert (await call("POST", "/v1/ai/memory", json={"enabled": True}))[0] == 504
    assert not server.lock.locked()


@pytest.mark.asyncio
async def test_api_cleanup_failure_still_closes_application(monkeypatch, unused_tcp_port):
    value = settings()
    stop = asyncio.Event()
    closed = []
    real_shutdown = __import__("app.container", fromlist=["Application"]).Application.shutdown
    async def shutdown(application):
        closed.append(True)
        await real_shutdown(application)
    async def session(**kwargs):
        kwargs["services"].runtime_state.set_twitch_connection_state("connected")
        stop.set()
        await kwargs["stop_event"].wait()
    async def fail_close(server):
        # Close the socket first; then exercise the runtime's failure path.
        if server.runner:
            await server.runner.cleanup()
        raise OSError("private-cleanup-sentinel")
    monkeypatch.setattr("app.container.Application.shutdown", shutdown)
    monkeypatch.setattr("app.bot_runtime.run_twitch_bot", session)
    monkeypatch.setattr(ManagementAPI, "close", fail_close)
    assert await headless.run_headless(value, AppSettings(), stop, startup_timeout=5, shutdown_timeout=2,
        management_config=ManagementConfig(TOKEN, port=unused_tcp_port)) == 1
    assert closed == [True]


@pytest.mark.asyncio
async def test_headless_api_stop_start_keeps_supervisor_and_state(monkeypatch, unused_tcp_port):
    value = settings()
    stop = asyncio.Event()
    sessions = []
    async def session(**kwargs):
        sessions.append(kwargs["services"])
        kwargs["services"].runtime_state.set_twitch_connection_state("connected")
        await kwargs["stop_event"].wait()
    monkeypatch.setattr("app.bot_runtime.run_twitch_bot", session)
    config = ManagementConfig(TOKEN, port=unused_tcp_port)
    worker = asyncio.create_task(headless.run_headless(value, AppSettings(), stop,
        startup_timeout=5, shutdown_timeout=2, management_config=config))
    try:
        async with aiohttp.ClientSession(headers={"Authorization": "Bearer " + TOKEN}) as client:
            for _ in range(100):
                if sessions:
                    break
                await asyncio.sleep(0.02)
            assert sessions
            for path in ("stop", "start", "stop", "start"):
                async with client.post(f"http://127.0.0.1:{unused_tcp_port}/v1/bot/{path}", json={}) as response:
                    assert response.status == 200, await response.text()
                await asyncio.sleep(0.15)
                assert not worker.done()
            assert len(sessions) == 3 and sessions[0] is sessions[-1]
    finally:
        stop.set()
        assert await asyncio.wait_for(worker, 5) == 0
    with socket.socket() as probe:
        assert probe.connect_ex(("127.0.0.1", unused_tcp_port)) != 0


def test_private_bind_token_files_and_secret_safe_configuration(tmp_path, monkeypatch):
    with pytest.raises(ValueError):
        load_management_token()
    path = tmp_path / "token"
    path.write_text(TOKEN + "\n", encoding="ascii")
    monkeypatch.setenv("HEETKIT_MANAGEMENT_TOKEN_FILE", str(path))
    assert load_management_token() == TOKEN
    assert "HEETKIT_MANAGEMENT_TOKEN" not in __import__("os").environ
    assert TOKEN not in repr(ManagementConfig(TOKEN))
    monkeypatch.setenv("HEETKIT_MANAGEMENT_TOKEN", TOKEN)
    with pytest.raises(ValueError):
        load_management_token()
    monkeypatch.delenv("HEETKIT_MANAGEMENT_TOKEN")
    for raw in (b"short", b"x" * 1025, b"\xff" * 45, TOKEN.encode() + b"\nextra"):
        path.write_bytes(raw)
        with pytest.raises(ValueError) as error:
            load_management_token()
        assert TOKEN not in str(error.value)
    for host in ("8.8.8.8", "example.com", "0.0.0.0", "224.0.0.1"):
        with pytest.raises(ValueError):
            ManagementConfig(TOKEN, host=host)
    assert ManagementConfig(TOKEN, host="0.0.0.0", allowed_host="127.0.0.1:8765").authorities == {"127.0.0.1:8765"}
