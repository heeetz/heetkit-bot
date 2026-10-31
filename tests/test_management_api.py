"""Private HTTP integration against synthetic profiles and the real shared core."""

import asyncio
import hashlib
import json
import logging
import socket
import ssl
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock

import aiohttp
import pytest
from aiohttp import web

from app import headless
from app.app_settings import AppSettings, AppSettingsStore
from app.bot_runtime import BotRuntime
from app.config.profile_settings import apply_ai_app_settings
from app.config.settings import Settings
from app.container import build_application
from app.management_api import ManagementAPI, ManagementConfig, load_management_token
from app.runtime_paths import RuntimePaths, prepare_runtime_data
from app.utils.logging import RecentLogBuffer, OperatorActivityHandler, event_metadata
from app.services.contracts import AIGenerationDetails, AIReply


TOKEN = "synthetic_management_token_" + "x" * 32
REMOTE_ORIGIN = "https://server.example-tailnet.ts.net"


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
    paths.tokens.write_text(json.dumps({"100": {"token": "synthetic-access", "refresh": "synthetic-refresh"}}), encoding="utf-8")
    return value


@pytest.fixture
async def api(unused_tcp_port):
    app = build_application(settings())
    AppSettingsStore(RuntimePaths.default().app_settings).update_operation_mode("manual")
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


async def test_announcements_authenticated_settings_status_and_shared_monitor(api):
    from app.announcements import AnnouncementStore
    from uuid import uuid4
    server, call = api
    assert (await call("GET", "/v1/announcements", headers={"Authorization": ""}))[0] == 401
    assert (await call("GET", "/v1/announcements"))[1] == {"ok": True, "announcements": []}
    raw = {"id": str(uuid4()), "name": "Community", "enabled": True, "messages": ["Join us"],
        "message_mode": "single", "interval_seconds": 60, "min_messages": 1,
        "stream_availability": "live_only", "delivery_mode": "highlighted"}
    assert (await call("POST", "/v1/announcements", json={"announcements": [raw]}))[1]["ok"]
    row = (await call("GET", "/v1/announcements"))[1]["announcements"][0]
    assert {key: value for key, value in row.items() if key != "status"} == raw
    assert row["status"]["next_run_at"] is None
    assert not server.policy._monitoring  # Manual disconnected does not poll
    saved = AnnouncementStore(server.runtime.application.announcements._path)
    assert saved.list()[0].to_json() == raw
    for payload in ({"announcements": [{**raw, "interval_seconds": 1}]},
                    {"announcements": [{**raw, "status": {}}]}, {"announcements": [raw], "extra": True}):
        assert (await call("POST", "/v1/announcements", json=payload))[0] == 400
    # Collection bounds permit more than the ordinary 64 KiB body, still bounded.
    large = [{**raw, "id": str(uuid4()), "messages": ["x" * 450] * 30, "message_mode": "random"} for _ in range(6)]
    assert len(json.dumps({"announcements": large})) > 65536
    assert (await call("POST", "/v1/announcements", json={"announcements": large}))[1]["ok"]
    assert len((await call("GET", "/v1/announcements"))[1]["announcements"]) == 6
    assert (await call("POST", "/v1/announcements", json={"announcements": []}))[1]["ok"]


async def test_analytics_private_scoped_windows_controls_and_memory_limits(api):
    server, call = api
    app = server.runtime.application
    collector = app.services.analytics
    for path, payload in (("/v1/analytics/query", {"days": 7}), ("/v1/analytics/configure", {"enabled": False}),
                          ("/v1/analytics/reset", {"confirmed": True}), ("/v1/ai/memory/limits", {"stored": 10, "context": 2}),
                          ("/v1/ai/balance", {"provider": "deepseek", "refresh": True})):
        assert (await call("POST", path, json=payload, headers={"Authorization": ""}))[0] == 401
        assert (await call("POST", path, json=payload, headers={"Origin": "https://evil.test"}))[0] == 403
    assert (await call("GET", "/v1/ai/memory/limits", headers={"Authorization": ""}))[0] == 401
    collector.record("command.attempts", channel_id="200", dimension="ping", value=4)
    collector.record("command.success", channel_id="200", dimension="ping", value=1)
    collector.record("command.skipped", channel_id="200", dimension="ping", value=3)
    collector.record("ai.attempts", channel_id="playground", dimension="deepseek/test", value=99)
    collector.record("command.attempts", channel_id="201", dimension="other", value=77)
    await collector.flush()
    for days in (1, 7, 30, 60):
        status, result, _ = await call("POST", "/v1/analytics/query", json={"days": days})
        assert status == 200 and result["ok"] and len(result["series"]) == days
        assert result["totals"]["command.attempts"] == 4
        assert result["totals"]["command.skipped"] == 3
        assert "ai.attempts" not in result["totals"]
        assert result["retained_users"] == 0 and result["channel_id"] == "200"
        assert not result["connected"] and "data_start" in result["metadata"]
    for payload in ({"days": True}, {"days": 2}, {"days": "7"}, {"channel_id": "201"}, {"days": 7, "extra": 1}):
        assert (await call("POST", "/v1/analytics/query", json=payload))[0] == 400
    for stored, context in ((0, 1), (501, 1), (10, 51), (5, 6), (True, 1), (10, "2")):
        assert (await call("POST", "/v1/ai/memory/limits", json={"stored": stored, "context": context}))[0] == 400
    assert (await call("POST", "/v1/ai/memory/limits", json={"stored": 10, "context": 2}))[1]["ok"]
    assert (await call("GET", "/v1/ai/memory/limits"))[1] == {"ok": True, "stored": 10, "context": 2}
    saved = AppSettingsStore(RuntimePaths.default().app_settings).snapshot().ai
    assert (saved.history_max_entries, saved.context_max_entries) == (10, 2)
    assert (await call("POST", "/v1/analytics/configure", json={"enabled": False}))[1]["ok"]
    assert not (await call("POST", "/v1/analytics/query", json={}))[1]["enabled"]
    assert (await call("POST", "/v1/analytics/reset", json={"confirmed": False}))[0] == 400
    assert (await call("POST", "/v1/analytics/reset", json={"confirmed": True}))[1]["ok"]
    assert (await call("POST", "/v1/analytics/query", json={}))[1]["totals"] == {}
    assert (await collector.snapshot("playground"))["rows"] == []
    assert (await call("POST", "/v1/analytics/configure", json={"enabled": "false"}))[0] == 400
    assert (await call("POST", "/v1/analytics/configure", json={"enabled": True}))[1]["ok"]
    app.services.users.retained_count = AsyncMock(side_effect=OSError("private path"))
    app.settings.twitch_channel_user_id = ""
    missing = (await call("POST", "/v1/analytics/query", json={}))[1]
    assert missing["channel_id"] is None and missing["retained_users"] is None


async def test_balance_shared_service_secure_key_and_mocked_refresh(api, monkeypatch):
    from pydantic import SecretStr
    server, call = api
    app = server.runtime.application
    app.settings.deepseek_api_key = SecretStr("balance-key-private-sentinel")
    get = AsyncMock(return_value={"ok": True, "provider": "deepseek", "state": "available", "balances": [
        {"currency": "USD", "total_balance": "12.30", "granted_balance": "0", "topped_up_balance": "12.30"}], "updated_at": "2026-10-30T10:00:00Z"})
    monkeypatch.setattr("app.services.ai_balance.AIBalance.get", get)
    result = (await call("POST", "/v1/ai/balance", json={"provider": "deepseek", "refresh": True}))[1]
    assert result["state"] == "available" and "sentinel" not in json.dumps(result)
    get.assert_awaited_once_with("deepseek", "balance-key-private-sentinel", refresh=True)
    for payload in ({"provider": "invalid"}, {"provider": "deepseek", "refresh": 1}, {"provider": "deepseek", "key": "injected"}):
        assert (await call("POST", "/v1/ai/balance", json=payload))[0] == 400


async def test_command_restrictions_authenticated_identity_errors_private_notes_and_immediate_removal(api, monkeypatch):
    server, call = api
    app = server.runtime.application
    assert (await call("GET", "/v1/command-restrictions", headers={"Authorization": ""}))[0] == 401
    raw = {"username": "viewer", "command_ids": ["ask"], "expires_at": None, "note": "PRIVATE RESTRICTION NOTE"}
    assert (await call("POST", "/v1/command-restrictions/save", json={"data": raw},
                       headers={"Authorization": ""}))[0] == 401
    unresolved = (await call("POST", "/v1/command-restrictions/save", json={"data": raw}))[1]
    assert not unresolved["ok"] and "verified Twitch user ID" in unresolved["error"]
    monkeypatch.setattr(app.services.twitch, "resolve_user_id", AsyncMock(return_value="123"))
    # Every factory command stays selectable, even hidden/admin/disabled/removed.
    app.services.runtime_state.remove_builtin_command("fate")
    app.services.runtime_state.apply_command_settings("ask", primary_name="question")
    result = (await call("POST", "/v1/command-restrictions/save", json={"data": raw}))[1]
    assert result["ok"]
    assert {row["id"] for row in result["commands"]} == {row.name for row in app.registry.definitions()}
    assert {"ask", "tg", "erase", "seen", "commands", "help", "fate"} <= {row["id"] for row in result["commands"]}
    assert next(row["label"] for row in result["commands"] if row["id"] == "ask") == "!question"
    rule = result["restrictions"][0]
    assert rule["channel_id"] == "200" and rule["twitch_user_id"] == "123"
    assert rule["note"] == raw["note"]
    assert app.services.command_restrictions.match("200", "123", "ask")
    for changes in ({"note": "x" * 201}, {"command_ids": ["optout"]}, {"twitch_user_id": "456"}):
        invalid = (await call("POST", "/v1/command-restrictions/save", json={"data": {**raw, **changes}}))[1]
        assert not invalid["ok"]
        assert raw["note"] not in json.dumps(invalid)
    updated = (await call("POST", "/v1/command-restrictions/save",
                         json={"data": {**raw, "id": rule["id"], "command_ids": []}}))[1]
    assert updated["ok"] and app.services.command_restrictions.match("200", "123", "commands")
    from app.twitch.events import IncomingChatMessage, ChatAuthor
    cooldown = Mock()
    monkeypatch.setattr(app.dispatcher._cooldowns, "check_and_record", cooldown)
    for definition in app.registry.definitions():
        name = app.services.runtime_state.get_command_settings(definition.name).primary_name
        incoming = IncomingChatMessage("channel", "!" + name, ChatAuthor("123", "renamed"),
                                       AsyncMock(), channel_id="200")
        assert await app.dispatcher.dispatch(incoming, app.services)
        incoming.respond.assert_not_awaited()
    cooldown.assert_not_called()
    assert (await call("GET", "/v1/command-restrictions"))[1] == updated
    assert raw["note"] not in json.dumps((await call("POST", "/v1/logs/recent", json={}))[1])
    removed = (await call("POST", "/v1/command-restrictions/remove", json={"restriction_id": rule["id"]}))[1]
    assert removed["ok"] and removed["restrictions"] == []
    assert app.services.command_restrictions.match("200", "123", "ask") is None


async def test_optout_authenticated_management_shared_storage_and_chat_updates(api, monkeypatch):
    server, call = api
    services = server.runtime.application.services
    for path, data in (("list", {}), ("add", {"username": "viewer"}),
                       ("withdraw", {"twitch_user_id": "123", "confirmed": True})):
        assert (await call("POST", "/v1/privacy/opt-outs/" + path, json=data,
                           headers={"Authorization": ""}))[0] == 401
    assert not (await call("POST", "/v1/privacy/opt-outs/add", json={"username": "unknown"}))[1]["ok"]
    monkeypatch.setattr(services.twitch, "resolve_user_id", AsyncMock(return_value="123"))
    added = (await call("POST", "/v1/privacy/opt-outs/add", json={"username": "viewer"}))[1]
    assert added["ok"] and added["users"][0]["username"] == "viewer"
    assert await services.users.is_storage_opted_out("123")
    # Chat uses the same repository; a fresh management read sees its update.
    await services.users.opt_out("456", username="chatviewer")
    listing = (await call("POST", "/v1/privacy/opt-outs/list", json={"query": "chat", "limit": 1}))[1]
    assert listing["total"] == 1 and listing["users"][0]["twitch_user_id"] == "456"
    for invalid in ({"limit": 1000}, {"offset": -1}, {"query": []}):
        assert (await call("POST", "/v1/privacy/opt-outs/list", json=invalid))[0] == 400
    assert (await call("POST", "/v1/privacy/opt-outs/withdraw",
                       json={"twitch_user_id": "123", "confirmed": False}))[0] == 400
    assert (await call("POST", "/v1/privacy/opt-outs/withdraw",
                       json={"twitch_user_id": "123", "confirmed": True}))[1]["ok"]
    assert not await services.users.is_storage_opted_out("123")


async def test_global_ai_scope_and_legacy_management_no_invisible_blocks(api, monkeypatch):
    server, call = api
    app = server.runtime.application
    services = app.services
    services.ai_user_blocks.block("unresolved")
    listing = (await call("GET", "/v1/command-restrictions"))[1]
    row = listing["restrictions"][0]
    assert row["identity_state"] == "unresolved" and row["twitch_user_id"] is None
    assert row["channel_id"] == "200" and not services.ai_user_blocks.list()
    raw = {"username": "viewer", "scope": "global_ai", "command_ids": ["ask"], "expires_at": None, "note": "private"}
    monkeypatch.setattr(services.twitch, "resolve_user_id", AsyncMock(return_value="123"))
    saved = (await call("POST", "/v1/command-restrictions/save", json={"data": raw}))[1]
    assert saved["ok"] and services.command_restrictions.match("999", "123", "ask")
    assert not services.command_restrictions.match("999", "123", "commands")
    assert not (await call("POST", "/v1/command-restrictions/save", json={"data": {**raw, "command_ids": []}}))[1]["ok"]
    retry = {key: row[key] for key in ("id", "username", "command_ids", "expires_at", "note", "scope")}
    assert (await call("POST", "/v1/command-restrictions/save", json={"data": retry}))[1]["ok"]
    assert services.command_restrictions.get(row["id"]).twitch_user_id == "123"
    # Factory reset preserves restrictions and opt-outs.
    await services.users.opt_out("456", username="other")
    assert (await call("POST", "/v1/commands/reset-all", json={}))[1]["ok"]
    assert len(services.command_restrictions.list()) == 2
    assert await services.users.is_storage_opted_out("456")


async def test_ai_setup_save_reload_validation_and_guide_use_authenticated_shared_operations(api):
    server, call = api
    status, result, _ = await call("GET", "/v1/ai/setup")
    assert status == 200 and {row["id"] for row in result["providers"]} == {"gemini", "deepseek", "openai"}
    assert all("value" not in row["credential"] for row in result["providers"])
    settings = result["settings"]
    settings.update(shared_instructions="Owner custom instructions", max_question_length=42, max_answer_length=120)
    assert (await call("POST", "/v1/ai/setup", json={"settings": settings}))[1]["ok"]
    assert (await call("GET", "/v1/ai/setup"))[1]["settings"] == settings
    settings["primary"]["thinking"] = "invented"
    status, result, _ = await call("POST", "/v1/ai/setup", json={"settings": settings})
    assert status == 400 and "Thinking choice" in result["error"]
    assert (await call("GET", "/v1/ai/setup"))[1]["settings"]["primary"]["thinking"] != "invented"
    status, result, _ = await call("POST", "/v1/setup/guide", json={"dismissed": True, "ai_skipped": True})
    assert status == 200 and result["dismissed"] and result["ai_skipped"]
    assert server.service.get_setup_guide() == result
    settings["primary"]["thinking"] = "default"
    settings["shared_instructions"] = "🙂" * 20000
    assert (await call("POST", "/v1/ai/setup", json={"settings": settings}))[1]["ok"]
    assert (await call("GET", "/v1/ai/setup"))[1]["settings"]["shared_instructions"] == "🙂" * 20000


async def test_playground_routes_authenticate_and_isolate_the_shared_slot(api):
    from app.webview_host import WebUIBridge
    from types import SimpleNamespace

    server, call = api
    control = server.runtime.application.ai_playground
    entered, release = asyncio.Event(), asyncio.Event()

    async def generate(**kwargs):
        assert kwargs == {"prompt": "Synthetic question", "user_id": "", "memory_context": None, "stream_category": None}
        entered.set()
        await release.wait()
        return AIReply("Synthetic answer", True, generation=AIGenerationDetails("DeepSeek", "deepseek-v4-pro", "high"))

    control.services.ai.generate_reply = generate
    for action, payload in (("start", {"prompt": "Synthetic question"}),
                            ("result", {"request_id": "unknown"}), ("cancel", {"request_id": "unknown"})):
        assert (await call("POST", "/v1/ai/playground/" + action, json=payload, headers={"Authorization": ""}))[0] == 401
    async def session():
        return {"Authorization": "Bearer " + (await call("POST", "/v1/session", json={}))[1]["token"]}
    owner, other = await session(), await session()
    status, started, headers = await call("POST", "/v1/ai/playground/start", json={"prompt": "Synthetic question"}, headers=owner)
    assert status == 200 and headers["Cache-Control"] == "no-store"
    await entered.wait()
    # Native and HTTP adapters use the same application's single request slot.
    desktop = WebUIBridge(SimpleNamespace(application=server.runtime.application))
    assert not (await desktop._start_ai_playground("duplicate"))["ok"]
    payload = {"request_id": started["request_id"]}
    for headers in (other, {}):
        for action in ("result", "cancel"):
            status, body, _ = await call("POST", "/v1/ai/playground/" + action, json=payload, headers=headers)
            assert status == 400 and "Synthetic" not in str(body)
    assert (await call("POST", "/v1/ai/playground/start", json={"prompt": "duplicate"}, headers=other))[0] == 400
    assert (await call("GET", "/v1/status", headers=owner))[0] == 200  # Generation never holds the HTTP lock.
    release.set()
    await control.task
    status, result, _ = await call("POST", "/v1/ai/playground/result", json=payload, headers=owner)
    assert status == 200 and result["text"] == "Synthetic answer"
    assert result["generation"]["provider"] == "DeepSeek" and result["generation"]["thinking"] == "high"
    with pytest.raises(ValueError):
        await desktop._get_ai_playground_result(started["request_id"])
    for payload in ({"prompt": 3}, {"prompt": "x" * 301}, {"prompt": "hello", "owner": "forged"}):
        assert (await call("POST", "/v1/ai/playground/start", json=payload, headers=owner))[0] == 400


@pytest.mark.parametrize("reason", ["logout", "expiry", "eviction", "shutdown"])
async def test_playground_session_end_revokes_results_and_cancels_once(api, monkeypatch, reason):
    server, call = api
    monkeypatch.setattr("app.management_api.MAX_SESSIONS", 1)
    token = (await call("POST", "/v1/session", json={}))[1]["token"]
    owner = hashlib.sha256(token.encode("ascii")).digest()
    headers = {"Authorization": "Bearer " + token}
    if reason == "expiry":
        server.sessions[owner] = time.monotonic() + 0.2
    entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    control = server.runtime.application.ai_playground

    async def stubborn(**kwargs):
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cleaning.set()
            await release.wait()
            return AIReply("PRIVATE late answer", True)

    control.services.ai.generate_reply = stubborn
    started = (await call("POST", "/v1/ai/playground/start", json={"prompt": "Synthetic question"}, headers=headers))[1]
    await entered.wait()
    shutdown = None
    if reason == "logout":
        assert (await call("POST", "/v1/session/logout", json={}, headers=headers))[0] == 200
    elif reason == "eviction":
        assert (await call("POST", "/v1/session", json={}))[0] == 200
    elif reason == "shutdown":
        shutdown = asyncio.create_task(server.close())
    await asyncio.wait_for(cleaning.wait(), 2)
    task = control.task
    try:
        assert not control.start("duplicate during cleanup")["ok"]
        with pytest.raises(ValueError):
            control.get(started["request_id"], owner=owner)
        control.revoke(owner)  # Repeated revocation cannot interrupt provider cleanup.
        await asyncio.sleep(0)
        assert not task.done()
    finally:
        release.set()
        await task
        if shutdown is not None:
            await shutdown
    assert task.result() == {"status": "cancelled"}
    assert control.request_id is None


async def test_playground_http_timeout_and_errors_never_expose_provider_payloads(api, monkeypatch, caplog):
    server, call = api
    control = server.runtime.application.ai_playground
    control.services.ai.generate_reply = AsyncMock(side_effect=RuntimeError("PRIVATE credential and prompt"))
    async def run():
        started = (await call("POST", "/v1/ai/playground/start", json={"prompt": "Synthetic question"}))[1]
        await control.task
        return (await call("POST", "/v1/ai/playground/result", json={"request_id": started["request_id"]}))[1]
    result = await run()
    assert result["status"] == "api_error" and "PRIVATE" not in str(result) + caplog.text
    cancelled = asyncio.Event()
    async def waiting(**kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    control.services.ai.generate_reply = waiting
    monkeypatch.setattr("app.services.ai_playground.AI_REQUEST_TIMEOUT_SECONDS", 0.02)
    result = await run()
    assert result["status"] == "timeout" and cancelled.is_set()


async def test_server_availability_http_save_reset_and_monitor_demand(api, monkeypatch):
    server, call = api
    async def offline(*args):
        return False
    monkeypatch.setattr(server.runtime.application.services.twitch, "get_broadcaster_live", offline)
    payload = {"command_name": "ask", "enabled": True, "per_user_seconds": 0,
        "global_seconds": 0, "permission": "USER", "options": {
            "primary_name": "question", "aliases": ["ask"], "stream_availability": "live_only"}}
    _, result, _ = await call("POST", "/v1/commands/save", json=payload)
    assert result["ok"]
    _, result, _ = await call("GET", "/v1/commands")
    ask = next(item for item in result["commands"] if item["name"] == "ask")
    assert ask["stream_availability"] == "live_only" and ask["saved"]
    assert ask["primary_name"] == "question" and ask["aliases"] == ["ask"]
    assert ask["default_settings"]["stream_availability"] == "anytime"
    assert not server.policy._monitoring  # Manual is stopped.
    # Exercise demand notification through the actual fixed HTTP dispatcher,
    # without starting a real Twitch session or calling a provider.
    server.policy.desired_running = True
    _, result, _ = await call("POST", "/v1/commands/save", json=payload)
    assert result["ok"] and server.policy._monitoring
    await call("POST", "/v1/commands/reset", json={"command_name": "ask"})
    assert not server.policy._monitoring
    assert server.runtime.application.services.runtime_state.get_command_settings("ask").primary_name == "ask"
    _, result, _ = await call("POST", "/v1/commands/save", json={**payload,
        "options": {"stream_availability": "invalid"}})
    assert not result["ok"]
    _, result, _ = await call("POST", "/v1/custom-commands/save", json={"command": {
        "name": "crosshair", "enabled": True, "responses": ["crosshair"], "permission": "USER",
        "per_user_seconds": 0, "global_seconds": 0, "aliases": [], "stream_availability": "offline_only"}})
    assert result["ok"] and server.policy._monitoring
    _, result, _ = await call("GET", "/v1/custom-commands")
    custom = result["commands"][0]
    assert custom["stream_availability"] == "offline_only"
    await call("POST", "/v1/custom-commands/delete", json={"identifier": custom["id"]})
    assert not server.policy._monitoring


@pytest.mark.asyncio
async def test_unrelated_cookies_are_ignored_without_granting_authority(api):
    server, call = api
    origin = f"http://127.0.0.1:{server.config.port}"
    cookie = "unrelated=private-cookie-sentinel; admin=" + TOKEN
    browser = {"Cookie": cookie, "Origin": origin, "Sec-Fetch-Site": "same-origin"}
    for method, path in (("GET", "/v1/status"), ("POST", "/v1/session"),
                         ("POST", "/v1/ai/memory")):
        status, body, headers = await call(method, path, headers=browser | {"Authorization": ""},
            **({"json": {}} if method == "POST" else {}))
        assert status == 401 and "private-cookie-sentinel" not in json.dumps(body)
        assert "Set-Cookie" not in headers and not server.sessions
    status, body, headers = await call("POST", "/v1/session", json={}, headers=browser)
    assert status == 200 and "Set-Cookie" not in headers
    browser["Authorization"] = "Bearer " + body["token"]
    assert (await call("GET", "/v1/status", headers=browser))[0] == 200
    assert (await call("POST", "/v1/ai/memory", json={"enabled": False}, headers=browser))[0] == 200
    assert not server.runtime.application.services.runtime_state.ai_memory_enabled
    for change in ({"Origin": "http://evil.test"}, {"Origin": "null"},
                   {"Host": "evil.test"}, {"Sec-Fetch-Site": "cross-site"},
                   {"Sec-Fetch-Site": "same-site"}):
        assert (await call("POST", "/v1/ai/memory", json={"enabled": True}, headers=browser | change))[0] == 403
    assert not server.runtime.application.services.runtime_state.ai_memory_enabled
    assert (await call("POST", "/v1/session/logout", json={}, headers=browser))[0] == 200
    assert (await call("GET", "/v1/status", headers=browser))[0] == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("authority", ["127.0.0.2:8765", "127.23.45.67:9765", "[::1]:9765"])
async def test_exact_loopback_origin_uses_published_authority_not_container_port(api, authority):
    server, call = api
    server.config = ManagementConfig(TOKEN, host="0.0.0.0", port=server.config.port, allowed_host=authority)
    headers = {"Host": authority, "Origin": "http://" + authority, "Sec-Fetch-Site": "same-origin",
               "Cookie": "unrelated=value"}
    assert (await call("POST", "/v1/session", json={}, headers=headers))[0] == 200
    for origin in ("http://127.0.0.1:8765", "http://localhost:8765", "http://" + authority + "/",
                   "http://127.evil.test:8765", "http://127.0.0.2:9999"):
        assert (await call("POST", "/v1/session", json={}, headers=headers | {"Origin": origin}))[0] == 403
    assert (await call("POST", "/v1/session", json={}, headers=headers | {"Host": "127.0.0.1:8765"}))[0] == 403
    for name, value in (("Host", authority), ("Origin", "http://" + authority),
                        ("Authorization", "Bearer " + TOKEN)):
        # Raw HTTP preserves duplicates that HTTP clients may normalize away.
        duplicates = list(headers.items()) + [("Authorization", "Bearer " + TOKEN), (name, value)]
        fields = "\r\n".join(f"{key}: {item}" for key, item in duplicates)
        raw = f"POST /v1/session HTTP/1.1\r\n{fields}\r\nContent-Type: application/json\r\nContent-Length: 2\r\n\r\n{{}}"
        reader, writer = await asyncio.open_connection("127.0.0.1", server.config.port)
        try:
            writer.write(raw.encode("ascii"))
            await writer.drain()
            response = await asyncio.wait_for(reader.read(), 2)
            assert response.split(b"\r\n", 1)[0].split()[1] in (b"400", b"401", b"403"), name
        finally:
            writer.close()
            await writer.wait_closed()


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


async def test_operation_mode_auth_validation_persistence_and_disabled_start(api, monkeypatch):
    server, call = api
    for headers, expected in (({"Authorization": ""}, 401), ({"Origin": "http://evil.test"}, 403)):
        assert (await call("POST", "/v1/bot/mode", json={"mode": "always_on"}, headers=headers))[0] == expected
    assert server.policy.mode == "manual"
    for payload in ({}, {"mode": "future"}, {"mode": []}, {"mode": True},
                    {"mode": "manual", "path": "private-sentinel"}):
        status, result, _ = await call("POST", "/v1/bot/mode", json=payload)
        assert status == 400 and "private-sentinel" not in json.dumps(result)
    assert server.policy.mode == "manual"
    assert (await call("POST", "/v1/bot/mode", json={"mode": "disabled"}))[0] == 200
    assert (await call("POST", "/v1/bot/start", json={}))[0] == 400
    assert not server.runtime.bot_active
    for path in ("/v1/status", "/v1/snapshot", "/v1/diagnostics"):
        status, result, _ = await call("GET", path)
        operation = result["status"]["operation"] if path.endswith("snapshot") else result["operation"]
        assert status == 200 and operation["mode"] == "disabled"
        assert operation["stream_status"] == "unknown"
        assert "private-client-sentinel" not in json.dumps(operation)
    assert (await call("POST", "/v1/ai/memory", json={"enabled": False}))[0] == 200
    store = AppSettingsStore(RuntimePaths.default().app_settings)
    assert store.snapshot().startup.operation_mode == "disabled"
    assert not store.snapshot().ai.memory_enabled
    original = store._path.read_bytes()
    def fail(*args, **kwargs):
        raise OSError("private-path-sentinel")
    monkeypatch.setattr("app.app_settings.os.replace", fail)
    status, result, _ = await call("POST", "/v1/bot/mode", json={"mode": "always_on"})
    assert status == 500 and "private-path-sentinel" not in json.dumps(result)
    assert server.policy.mode == "disabled" and store._path.read_bytes() == original


@pytest.mark.asyncio
async def test_configuration_transfer_authenticated_preview_confirm_and_live_apply(api):
    from app.configuration_transfer import pack_configuration, unpack_configuration

    server, call = api
    for path in ("export", "preview", "import"):
        for headers, expected in (({"Authorization": ""}, 401), ({"Origin": "http://evil.test"}, 403)):
            assert (await call("POST", "/v1/configuration/" + path, json={}, headers=headers))[0] == expected
    status, exported, headers = await call("POST", "/v1/configuration/export", json={})
    assert status == 200 and headers["Cache-Control"] == "no-store"
    payload, _, _ = unpack_configuration(exported["archive_base64"])
    payload["ai"]["memory_enabled"] = False
    # Exercise the transfer-specific body allowance with an ordinary stored ZIP
    # larger than the API's normal 64 KiB JSON limit.
    payload["personalities"]["profile_instructions"] = "Portable instructions. " * 2100
    encoded = pack_configuration(payload)
    assert len(encoded) > 65536
    status, preview, _ = await call("POST", "/v1/configuration/preview", json={"archive_base64": encoded})
    assert status == 200 and preview["sections"] and preview["preserved"]
    assert server.runtime.application.services.runtime_state.ai_memory_enabled
    arguments = {"archive_base64": encoded, "preview_token": preview["preview_token"], "confirmed": False}
    assert (await call("POST", "/v1/configuration/import", json=arguments))[0] == 400
    arguments["confirmed"] = True
    assert (await call("POST", "/v1/configuration/import", json=arguments))[0] == 200
    assert not server.runtime.application.services.runtime_state.ai_memory_enabled
    assert server.runtime.application.services.runtime_state.profile_instructions.startswith("Portable instructions.")
    assert (await call("POST", "/v1/configuration/import", json=arguments))[0] == 400
    assert (await call("POST", "/v1/configuration/preview", json={"archive_base64": "private-sentinel"}))[0] == 400
    # Normal mutations retain their original body limit; no arbitrary filenames,
    # local paths, additional fields or download URLs enter the transport.
    assert (await call("POST", "/v1/ai/memory", json={"padding": "x" * 66000}))[0] == 413
    assert (await call("POST", "/v1/configuration/export", json={"path": "auth/tokens.json"}))[0] == 400
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
    clone_settings = apply_ai_app_settings(settings(), profile)
    # This verifies configuration stores; the running composition exclusively owns
    # the persistent database. Use an independent synthetic database for the clone.
    clone_settings.database_url = "sqlite+aiosqlite:///:memory:"
    clone = build_application(clone_settings)
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
        assert clone.services.command_restrictions.match("200", "123", "ask", "syntheticviewer")
        assert not clone.services.ai_user_blocks.list()
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
async def test_authenticated_activity_matches_desktop_without_raw_prose(api):
    from app.webview_host import WebUIBridge
    from types import SimpleNamespace
    server, call = api
    handler = OperatorActivityHandler(server.log_buffer)
    for kind, outcome, text in [("command.input", "received", "!ping <literal>"),
                                ("command.outcome", "cooldown", None),
                                ("chat.outgoing", "uncertain_send", "@viewer exact reply")]:
        record = logging.LogRecord("tests.activity", logging.WARNING, "", 0, "PRIVATE RAW PROSE", (), None)
        for key, value in event_metadata(kind, request_id="shared", command="ping", source="command",
                                         outcome=outcome, retry_after_seconds=12.5).items():
            setattr(record, key, value)
        record.event_text = text
        handler.emit(record)
    assert (await call("POST", "/v1/logs/recent", headers={"Authorization": ""}, json={}))[0] == 401
    status, body, headers = await call("POST", "/v1/logs/recent", json={})
    assert status == 200 and headers["Cache-Control"] == "no-store"
    desktop = WebUIBridge(SimpleNamespace(), log_buffer=server.log_buffer).get_recent_logs()
    assert body["entries"] == desktop["entries"]
    assert body["next_after_id"] == desktop["next_after_id"]
    assert "PRIVATE RAW PROSE" not in json.dumps(body)
    assert [entry["text"] for entry in body["entries"]] == ["!ping <literal>", None, "@viewer exact reply"]
    assert body["entries"][1]["context"]["retry_after_seconds"] == 12.5


@pytest.mark.asyncio
async def test_authenticated_correlation_and_filter_projection_is_sanitized(api):
    server, call = api
    handler = OperatorActivityHandler(server.log_buffer)
    for kind, outcome, reason in [("chat.correlation", "input_paused", "send_timeout"),
                                  ("chat.correlation", "input_dropped", "quarantine"),
                                  ("chat.correlation", "input_resumed", "quarantine_expired"),
                                  ("chat.filtered", "filters", "content_filter")]:
        record = logging.LogRecord("app.headless.chat", logging.INFO, "", 0, "PRIVATE prose", (), None)
        for key, value in event_metadata(kind, inherit_context=False, outcome=outcome,
                                         reason=reason, remaining_seconds=0, drop_count=2).items():
            setattr(record, key, value)
        record.event_text = "PRIVATE rejected text"
        handler.emit(record)
    assert (await call("POST", "/v1/logs/recent", headers={"Authorization": ""}, json={}))[0] == 401
    status, body, headers = await call("POST", "/v1/logs/recent", json={})
    assert status == 200 and headers["Cache-Control"] == "no-store"
    assert len(body["entries"]) == 4
    assert "PRIVATE" not in json.dumps(body)
    assert all(e["text"] is None for e in body["entries"])


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


@pytest.mark.parametrize("mode", ["always_on", "stream_only", "manual", "disabled"])
async def test_process_restarts_honor_modes_with_management_available(monkeypatch, unused_tcp_port, mode):
    value = settings()
    store = AppSettingsStore(RuntimePaths.default().app_settings)
    store.update_operation_mode(mode)
    sessions = []
    async def session(**kwargs):
        sessions.append(True)
        kwargs["services"].runtime_state.set_twitch_connection_state("connected")
        await kwargs["stop_event"].wait()
    async def offline(*args):
        return False
    monkeypatch.setattr("app.bot_runtime.run_twitch_bot", session)
    monkeypatch.setattr("app.services.twitch.TwitchAPIService.get_broadcaster_live", offline)
    for _ in range(2):
        stop = asyncio.Event()
        worker = asyncio.create_task(headless.run_headless(value, store.snapshot(), stop,
            startup_timeout=5, shutdown_timeout=2, management_config=ManagementConfig(TOKEN, port=unused_tcp_port)))
        try:
            async with aiohttp.ClientSession(headers={"Authorization": "Bearer " + TOKEN}) as client:
                for _ in range(200):
                    try:
                        async with client.get(f"http://127.0.0.1:{unused_tcp_port}/v1/status") as response:
                            body = await response.json()
                        if not body["operation"]["pending"]:
                            break
                    except aiohttp.ClientConnectionError:
                        pass
                    await asyncio.sleep(0.01)
                assert body["operation"]["mode"] == mode
                assert body["running"] == (mode == "always_on")
                if mode == "manual":
                    async with client.post(f"http://127.0.0.1:{unused_tcp_port}/v1/bot/start", json={}) as response:
                        assert response.status == 200
                    await asyncio.sleep(0.1)
                assert not worker.done()
        finally:
            stop.set()
            assert await asyncio.wait_for(worker, 5) == 0
    assert len(sessions) == (2 if mode in {"manual", "always_on"} else 0)


def _shutdown_task_frames(task):
    """Bounded await locations only: never task names, source lines or frame locals."""
    frames = []
    current = task.get_coro()
    for _ in range(16):
        code = getattr(current, "cr_code", None)
        frame = getattr(current, "cr_frame", None)
        if code is not None:
            frames.append((code.co_name, frame.f_lineno if frame is not None else None))
        current = getattr(current, "cr_await", None)
        if current is None:
            break
    return frames


@pytest.fixture
def shutdown_diagnostics(monkeypatch):
    """Retain phase durations and sample pending awaits before timeout cancellation."""
    from app.analytics import Analytics
    from app.container import Application
    from app.database.database import Database
    from app.operation_policy import OperationPolicy

    phases, applications = [], []
    build = headless.build_application
    def capture(value):
        application = build(value)
        applications.append(application)
        return application
    monkeypatch.setattr(headless, "build_application", capture)
    for owner, method in ((OperationPolicy, "close"), (BotRuntime, "stop_bot"),
                          (BotRuntime, "shutdown"), (Application, "shutdown"),
                          (Analytics, "close"), (Analytics, "flush"), (Database, "close")):
        def wrap(original, label):
            async def measured(*args, **kwargs):
                start = time.perf_counter()
                phases.append((label, "enter"))
                try:
                    return await original(*args, **kwargs)
                finally:
                    phases.append((label, round(time.perf_counter() - start, 6)))
            return measured
        monkeypatch.setattr(owner, method, wrap(getattr(owner, method), owner.__name__ + "." + method))
    cancel = headless._cancel_task
    async def capture_before_cancel(task, **kwargs):
        if getattr(task.get_coro(), "__name__", None) == "shutdown" and not task.done():
            tasks = [task, *(item for item in asyncio.all_tasks() if item is not task and not item.done())]
            pending = [_shutdown_task_frames(item) for item in tasks[:32]]
            logging.getLogger(__name__).warning("Shutdown deadline diagnostics: phases=%s pending=%s",
                phases[-32:], pending[:32])
        return await cancel(task, **kwargs)
    monkeypatch.setattr(headless, "_cancel_task", capture_before_cancel)
    return applications


async def test_shutdown_diagnostics_capture_before_cancellation(shutdown_diagnostics, caplog):
    entered = asyncio.Event()
    async def shutdown():
        private_payload = "PRIVATE-SHUTDOWN-SENTINEL"
        entered.set()
        await asyncio.Event().wait()
        return private_payload
    task = asyncio.create_task(shutdown(), name="PRIVATE-TASK-SENTINEL")
    await entered.wait()
    assert await headless._cancel_task(task)
    assert task.cancelled()
    assert "Shutdown deadline diagnostics" in caplog.text and "shutdown" in caplog.text
    assert "PRIVATE" not in caplog.text


async def test_shutdown_task_locations_exclude_private_locals_and_task_names():
    async def waiting():
        private_payload = "PRIVATE-DIAGNOSTIC-SENTINEL"
        await asyncio.Event().wait()
        return private_payload
    task = asyncio.create_task(waiting(), name="PRIVATE-TASK-SENTINEL")
    try:
        await asyncio.sleep(0)
        locations = _shutdown_task_frames(task)
        assert locations and len(locations) <= 16
        assert "PRIVATE" not in str(locations)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_terminal_twitch_failure_leaves_browser_management_alive(monkeypatch, unused_tcp_port, shutdown_diagnostics):
    value = settings()
    stop = asyncio.Event()
    failed = asyncio.Event()
    async def session(**kwargs):
        kwargs["services"].runtime_state.set_twitch_connection_state("auth_required")
        failed.set()
        await kwargs["stop_event"].wait()
    monkeypatch.setattr("app.bot_runtime.run_twitch_bot", session)
    worker = asyncio.create_task(headless.run_headless(value, AppSettings(), stop,
        startup_timeout=5, shutdown_timeout=2, management_config=ManagementConfig(TOKEN, port=unused_tcp_port)))
    try:
        await asyncio.wait_for(failed.wait(), 5)
        await asyncio.sleep(0.2)
        async with aiohttp.ClientSession(headers={"Authorization": "Bearer " + TOKEN}) as client:
            async with client.get(f"http://127.0.0.1:{unused_tcp_port}/v1/status") as response:
                body = await response.json()
                assert response.status == 200
            assert body["operation"]["error"] == "connection_failed"
            assert not body["operation"]["desired_running"]
            assert not worker.done()
            async with client.post(f"http://127.0.0.1:{unused_tcp_port}/v1/bot/mode", json={"mode": "disabled"}) as response:
                assert response.status == 200
    finally:
        stop.set()
        assert await asyncio.wait_for(worker, 5) == 0
    application = shutdown_diagnostics[0]
    assert application.database._retention_task is None
    assert application.services.analytics._connection is None
    assert application.services.analytics._task.done()


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


@pytest.mark.asyncio
async def test_browser_session_origin_expiry_revocation_and_capacity(api):
    server, call = api
    origin = f"http://127.0.0.1:{server.config.port}"
    headers = {"Origin": origin, "Sec-Fetch-Site": "same-origin"}
    for change in ({"Origin": "null"}, {"Origin": "https://evil.test"},
                   {"Sec-Fetch-Site": "same-site"},
                   {"Origin": origin + "/"}, {"Authorization": ""}):
        status, body, _ = await call("POST", "/v1/session", json={}, headers=headers | change)
        assert status in (401, 403)
        assert "token" not in body and not server.sessions
    status, body, response_headers = await call("POST", "/v1/session", json={}, headers=headers)
    assert status == 200 and body["expires_in"] == 3600
    token = body["token"]
    assert token != TOKEN and token not in repr(server.sessions)
    assert response_headers["Cache-Control"] == "no-store" and "Set-Cookie" not in response_headers
    browser = headers | {"Authorization": "Bearer " + token}
    assert (await call("GET", "/v1/session", headers=browser))[0] == 200
    assert (await call("GET", "/v1/snapshot", headers=browser))[0] == 200
    assert (await call("POST", "/v1/session", json={}, headers=browser))[0] == 401
    assert (await call("POST", "/v1/session/logout", json={}, headers=browser))[0] == 200
    assert (await call("GET", "/v1/status", headers=browser))[0] == 401
    for _ in range(9):
        _, body, _ = await call("POST", "/v1/session", json={}, headers=headers)
    assert len(server.sessions) == 8
    token = body["token"]
    digest = hashlib.sha256(token.encode()).digest()
    server.sessions[digest] = 0
    assert (await call("GET", "/v1/status", headers=browser | {"Authorization": "Bearer " + token}))[0] == 401
    assert len(server.sessions) == 7
    # Private plaintext browser origins are refused; an exact HTTPS origin works.
    server.config = ManagementConfig(TOKEN, port=server.config.port, allowed_host="192.168.0.5:8765")
    for scheme, expected in (("http", 403), ("https", 200)):
        assert (await call("POST", "/v1/session", json={}, headers={
            "Host": "192.168.0.5:8765", "Origin": scheme + "://192.168.0.5:8765",
            "Sec-Fetch-Site": "same-origin"}))[0] == expected


@pytest.mark.asyncio
async def test_session_queued_before_logout_cannot_mutate(api):
    server, call = api
    _, body, _ = await call("POST", "/v1/session", json={})
    token = body["token"]
    await server.lock.acquire()
    pending = asyncio.create_task(call("POST", "/v1/ai/memory", json={"enabled": False},
        headers={"Authorization": "Bearer " + token}))
    try:
        for _ in range(100):
            if server.active:
                break
            await asyncio.sleep(0.01)
        assert server.active == 1
        server.sessions.clear()
    finally:
        server.lock.release()
    assert (await pending)[0] == 401
    assert server.runtime.application.services.runtime_state.ai_memory_enabled


@pytest.mark.asyncio
async def test_built_frontend_delivery_is_allowlisted_and_isolated(api, tmp_path):
    server, call = api
    server.frontend = tmp_path / "ui"
    (server.frontend / "assets").mkdir(parents=True)
    (server.frontend / "index.html").write_text('<html><head></head><body><script src="./assets/index-test.js"></script></body></html>')
    (server.frontend / "assets/index-test.js").write_text('console.log("synthetic");')
    (server.frontend / "assets/index-test.css").write_text('body{color:white}')
    (server.frontend / "assets/private.json").write_text('private-sentinel')
    (server.frontend / "private.txt").write_text('private-sentinel')
    (server.frontend / "assets/index-test.js.map").write_text('private-sentinel')
    url = f"http://127.0.0.1:{server.config.port}"
    async with aiohttp.ClientSession(trust_env=False) as client:
        for path, kind in (("/", "text/html"), ("/index.html", "text/html"),
                           ("/assets/index-test.js", "text/javascript"), ("/assets/index-test.css", "text/css")):
            async with client.get(url + path) as response:
                text = await response.text()
                assert response.status == 200 and response.content_type == kind
                assert response.headers["Cache-Control"] == "no-store"
                assert response.headers["Cross-Origin-Resource-Policy"] == "same-origin"
                csp = response.headers["Content-Security-Policy"]
                assert "script-src 'self';" in csp and "frame-ancestors 'none'" in csp
                assert "private-sentinel" not in text
                if kind == "text/html":
                    assert '<meta name="heetkit-transport" content="http">' in text
        for path in ("/private.txt", "/assets/private.json", "/assets/index-test.js.map",
                     "/auth/tokens.json", "/.env", "/assets/%2e%2e/private.txt"):
            async with client.get(url + path) as response:
                assert response.status in (400, 404)
                assert "private-sentinel" not in await response.text()
        async with client.get(url + "/", headers={"Sec-Fetch-Site": "cross-site"}) as response:
            assert response.status == 403
        async with client.get(url + "/?token=private-sentinel") as response:
            assert response.status == 400
    (server.frontend / "assets/index-test.js").write_bytes(b"x" * (4 * 1024 * 1024 + 1))
    async with aiohttp.ClientSession() as client:
        async with client.get(url + "/assets/index-test.js") as response:
            assert response.status == 503
    assert (await call("GET", "/v1/status", headers={"Authorization": ""}))[0] == 401


@pytest.mark.asyncio
async def test_browser_presentation_routes_apply_save_and_log_cursor(api, monkeypatch):
    server, call = api
    for path in ("/v1/snapshot", "/v1/setup", "/v1/about"):
        status, body, _ = await call("GET", path)
        assert status == 200
        assert "private-client-sentinel" not in json.dumps(body) and TOKEN not in json.dumps(body)
        assert str(RuntimePaths.default().root) not in json.dumps(body)
    _, setup, _ = await call("GET", "/v1/setup")
    assert setup["credentials"][0]["configured"] and setup["twitch"]["client_id"] == "synthetic-client"
    assert (await call("POST", "/v1/credentials/replace", json={"name": "gemini_api_key", "value": "private-provider-sentinel"}))[0] == 200
    _, provider, _ = await call("GET", "/v1/ai/models")
    assert provider["settings"]["credential"]["configured"]
    assert "private-provider-sentinel" not in json.dumps(provider)
    command = {"command_name": "ping", "enabled": False, "per_user_seconds": 7,
               "global_seconds": 3, "permission": "MODERATOR"}
    assert (await call("POST", "/v1/commands/apply", json=command))[0] == 200
    ping = next(item for item in server.service.get_commands()["commands"] if item["name"] == "ping")
    assert not ping["enabled"] and not ping["saved"]
    for path, data in (("/v1/commands/responses/apply", {"name": "fate", "responses": ["Synthetic response"]}),
                       ("/v1/filters/apply", {"payload": {"words": ["blocked"], "phrases": [], "patterns": []}}),
                       ("/v1/ai/instructions/apply", {"prompt": "Synthetic instructions"}),
                       ("/v1/personalities/apply", {"personality": "neutral", "prompt": "Synthetic prompt"}),
                       ("/v1/commands/reset-all", {})):
        assert (await call("POST", path, json=data))[0] == 200
    async def discover(provider):
        assert provider == "gemini"
        return ["gemini-synthetic"]
    monkeypatch.setattr(server.runtime.application.services.ai, "discover_models", discover)
    assert (await call("POST", "/v1/ai/models/discover", json={}))[1]["models"] == ["gemini-synthetic"]
    record = logging.LogRecord("test", logging.INFO, "", 0, "private-chat-sentinel", (), None)
    server.log_buffer.append(record, "private-chat-sentinel")
    _, body, _ = await call("POST", "/v1/logs/recent", json={"limit": 1})
    assert body["entries"] == [] and body["next_after_id"] > 0
    record.event_kind = "twitch.connected"
    server.log_buffer.append(record, "private-chat-sentinel")
    _, body, _ = await call("POST", "/v1/logs/recent", json={"after_id": body["next_after_id"]})
    assert body["entries"][0]["source"] == "lifecycle" and body["entries"][0]["context"] == {}
    assert "private-chat-sentinel" not in json.dumps(body)


@pytest.mark.parametrize("origin", [
    "http://server.example.com", "https://*.example.com", "https://example.com/",
    "https://example.com/path", "https://user@example.com", "https://example.com?x=1",
    "https://example.com#fragment", "https://Example.com", "https://example.com.",
    "https://example..com", "https://-example.com", "https://example-.com",
    "https://localhost", "https://127.0.0.1", "https://example.com:443",
    "https://example.com:00444", "https://example.com:0", "https://example.com:65536",
    "https://\u00e9xample.com", "https://example.com\\evil.test", "https://example.com\n",
])
def test_remote_origin_is_strict_canonical_configuration(origin):
    with pytest.raises(ValueError):
        ManagementConfig(TOKEN, trusted_origin=origin, trusted_proxies=("127.0.0.1",))


def test_remote_proxy_configuration_has_no_implicit_trust():
    for kwargs in ({"trusted_origin": REMOTE_ORIGIN}, {"trusted_proxies": ("127.0.0.1",)},
                   {"twitch_redirect_uri": REMOTE_ORIGIN + "/oauth/callback"},
                   {"trusted_origin": REMOTE_ORIGIN, "trusted_proxies": ("0.0.0.0",)},
                   {"trusted_origin": REMOTE_ORIGIN, "trusted_proxies": ("127.0.0.0/8",)},
                   {"trusted_origin": REMOTE_ORIGIN, "trusted_proxies": ("localhost",)}):
        with pytest.raises(ValueError):
            ManagementConfig(TOKEN, **kwargs)
    common = {"trusted_origin": REMOTE_ORIGIN, "trusted_proxies": ("127.0.0.1",)}
    for redirect in ("http://server.example-tailnet.ts.net/oauth/callback", "https://evil.test/oauth/callback",
                     REMOTE_ORIGIN + "/wrong", REMOTE_ORIGIN + "/oauth/callback?x=1"):
        with pytest.raises(ValueError):
            ManagementConfig(TOKEN, **common, twitch_redirect_uri=redirect)
    with pytest.raises(ValueError):
        ManagementConfig(TOKEN, **common, allowed_host="127.0.0.1:8765")
    assert ManagementConfig(TOKEN, **common).authorities == {"server.example-tailnet.ts.net"}
    assert ManagementConfig(TOKEN, trusted_origin=REMOTE_ORIGIN + ":8443",
        trusted_proxies=("::1",)).authorities == {"server.example-tailnet.ts.net:8443"}


@pytest.mark.parametrize("options,redirect,enabled", [
    ({}, "http://localhost:8765/oauth/callback", True),
    ({"port": 9765}, "http://localhost:9765/oauth/callback", True),
    ({"host": "::1"}, "http://localhost:8765/oauth/callback", True),
    ({"host": "0.0.0.0", "allowed_host": "127.0.0.1:9765"}, "http://localhost:9765/oauth/callback", True),
    ({"host": "127.0.0.2"}, "http://localhost:8765/oauth/callback", False),
    ({"host": "0.0.0.0", "allowed_host": "127.0.0.2:9765"}, "http://localhost:9765/oauth/callback", False),
    ({"host": "192.168.1.2"}, "http://localhost:8765/oauth/callback", False),
    ({"trusted_origin": REMOTE_ORIGIN, "trusted_proxies": ("127.0.0.1",)}, "http://localhost:8765/oauth/callback", False),
    ({"trusted_origin": REMOTE_ORIGIN, "trusted_proxies": ("127.0.0.1",),
      "twitch_redirect_uri": REMOTE_ORIGIN + "/oauth/callback"}, REMOTE_ORIGIN + "/oauth/callback", True),
])
def test_server_callback_configuration_uses_management_port(options, redirect, enabled):
    config = ManagementConfig(TOKEN, **options)
    assert config.oauth_redirect_uri == redirect
    assert config.oauth_callback_enabled is enabled
    # Callback aliases never expand the management/API Host allowlist.
    if config.allowed_host:
        assert config.authorities == {config.allowed_host}


async def test_forwarding_is_rejected_outside_explicit_proxy_mode(api):
    _, call = api
    for header, value in (("Forwarded", "proto=https"), ("X-Forwarded-Host", "evil.test"),
                          ("X-Forwarded-For", "127.0.0.1"), ("X-Forwarded-Proto", "https")):
        assert (await call("GET", "/v1/status", headers={header: value}))[0] == 403


async def test_remote_host_origin_and_socket_peer_cannot_be_substituted(api):
    server, call = api
    server.config = ManagementConfig(TOKEN, port=server.config.port,
        trusted_origin=REMOTE_ORIGIN, trusted_proxies=("127.0.0.1",))
    headers = {"Host": "server.example-tailnet.ts.net", "Origin": REMOTE_ORIGIN,
               "X-Forwarded-Proto": "https", "X-Forwarded-Host": "server.example-tailnet.ts.net",
               "X-Forwarded-For": "100.100.100.100", "Sec-Fetch-Site": "same-origin"}
    assert (await call("POST", "/v1/session", json={}, headers=headers))[0] == 200
    for changes in ({"Host": "evil.test"}, {"Host": "server.example-tailnet.ts.net:443"},
                    {"Host": "server.example-tailnet.ts.net.evil.test"},
                    {"Origin": "http://server.example-tailnet.ts.net"}, {"Origin": REMOTE_ORIGIN + "/"},
                    {"Origin": "null"}, {"Origin": "https://evil.test"},
                    {"X-Forwarded-Proto": "http"}, {"X-Forwarded-Proto": "https,http"},
                    {"X-Forwarded-Host": "evil.test"}, {"X-Forwarded-For": "1.2.3.4, 127.0.0.1"},
                    {"Forwarded": "proto=https"}, {"X-Forwarded-Port": "443"},
                    {"Sec-Fetch-Site": "cross-site"}):
        assert (await call("POST", "/v1/session", json={}, headers=headers | changes))[0] == 403
    for name in ("Origin", "X-Forwarded-Proto", "X-Forwarded-Host", "X-Forwarded-For"):
        duplicate = list(headers.items()) + [(name, headers[name])]
        assert (await call("GET", "/v1/status", headers=duplicate))[0] == 403, name
    # aiohttp's client normalizes Host; use the wire to test duplicate authorities.
    reader, writer = await asyncio.open_connection("127.0.0.1", server.config.port)
    writer.write(b"GET /v1/status HTTP/1.1\r\nHost: server.example-tailnet.ts.net\r\nHost: evil.test\r\n\r\n")
    await writer.drain()
    assert b" 400 " in await reader.readline()  # Rejected by aiohttp's HTTP parser.
    writer.close()
    await writer.wait_closed()
    server.config = ManagementConfig(TOKEN, port=server.config.port,
        trusted_origin=REMOTE_ORIGIN, trusted_proxies=("127.0.0.2",))
    assert (await call("POST", "/v1/session", json={}, headers=headers))[0] == 403


async def test_https_termination_with_isolated_real_proxy(api, tmp_path, unused_tcp_port_factory):
    # One local test certificate and HTTPS proxy, no DNS, Tailscale or live accounts.
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    import ipaddress
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "isolated-test")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), False)
        .sign(key, hashes.SHA256()))
    cert_path, key_path = tmp_path / "proxy.pem", tmp_path / "proxy-key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(cert_path, key_path)
    trust = ssl.create_default_context(cafile=str(cert_path))
    server, _ = api
    server.config = ManagementConfig(TOKEN, port=server.config.port,
        trusted_origin=REMOTE_ORIGIN, trusted_proxies=("127.0.0.1",))
    async with aiohttp.ClientSession(trust_env=False) as upstream:
        async def proxy(request):
            # Same boundary as Tailscale Serve: overwrite forwarding information,
            # preserve Host/Origin, and never turn network identity into API auth.
            headers = {k: v for k, v in request.headers.items()
                       if not k.lower().startswith("x-forwarded-") and k.lower() != "forwarded"}
            headers.update({"X-Forwarded-Proto": "https", "X-Forwarded-Host": request.headers["Host"],
                            "X-Forwarded-For": request.remote})
            async with upstream.request(request.method, f"http://127.0.0.1:{server.config.port}" + request.raw_path,
                    data=await request.read(), headers=headers, allow_redirects=False) as response:
                return web.Response(body=await response.read(), status=response.status,
                    headers={k: v for k, v in response.headers.items() if k.lower() not in ("content-length", "connection")})
        application = web.Application()
        application.router.add_route("*", "/{path:.*}", proxy)
        runner = web.AppRunner(application, access_log=None)
        await runner.setup()
        proxy_port = unused_tcp_port_factory()
        await web.TCPSite(runner, "127.0.0.1", proxy_port, ssl_context=tls).start()
        try:
            async with aiohttp.ClientSession(trust_env=False) as browser:
                url = f"https://127.0.0.1:{proxy_port}"
                headers = {"Host": "server.example-tailnet.ts.net", "Origin": REMOTE_ORIGIN,
                           "Authorization": "Bearer " + TOKEN, "X-Forwarded-Host": "evil.test"}
                async with browser.post(url + "/v1/session", json={}, headers=headers, ssl=trust) as response:
                    assert response.status == 200
                    session = (await response.json())["token"]
                    assert "Set-Cookie" not in response.headers
                headers["Authorization"] = "Bearer " + session
                async with browser.get(url + "/v1/status", headers=headers, ssl=trust) as response:
                    assert response.status == 200
                headers.pop("Authorization")
                async with browser.get(url + "/v1/status", headers=headers, ssl=trust) as response:
                    assert response.status == 401
        finally:
            await runner.cleanup()
