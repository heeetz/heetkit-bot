"""First-run server setup against real private HTTP and synthetic providers only."""

import asyncio
import json
import logging
import os
import stat
from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode, urlsplit

import aiohttp
import pytest
from aiohttp import web
from yarl import URL
from twitchio.authentication.payloads import UserTokenPayload, ValidateTokenPayload
from twitchio.http import HTTPClient

from app.app_settings import AppSettingsStore
from app.bot_runtime import BotRuntime
from app.config.profile_settings import apply_twitch_app_settings
from app.config.settings import Settings
from app.container import build_application
from app.credentials import CredentialError, CredentialName
from app.management_api import ManagementAPI, ManagementConfig
from app.runtime_paths import RuntimePaths, prepare_runtime_data
from app.server_credentials import ServerCredentialManager, ServerCredentialStore
from app.server_setup import credential_manager
from app.twitch.client import CHAT_SCOPES, OAUTH_SCOPES, OAUTH_REDIRECT_URI, TwitchChatBot


TOKEN = "synthetic_management_token_" + "x" * 32
TWITCH = {"client_id": "test-client", "bot_username": "testbot", "bot_user_id": "100",
          "channel": "testchannel", "channel_user_id": "200"}
TWITCH_HTTP_REQUEST = HTTPClient.request


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    monkeypatch.setenv("HEETKIT_DATA_DIR", str(tmp_path / "profile"))
    async def forbidden(*args, **kwargs):
        raise AssertionError("No external provider requests in server setup tests")
    monkeypatch.setattr("httpx.AsyncClient.send", forbidden)
    monkeypatch.setattr("twitchio.http.HTTPClient.request", forbidden)


@pytest.fixture
async def api(unused_tcp_port):
    paths = RuntimePaths.default()
    settings = Settings(twitch_token_file=str(paths.tokens), database_url="sqlite+aiosqlite:///" + str(paths.database))
    prepare_runtime_data(settings.twitch_token_file, settings.database_url)
    store = AppSettingsStore(paths.app_settings)
    store.update_operation_mode("manual")
    runtime = BotRuntime(build_application(settings), logging.getLogger("test"), headless=True)
    await runtime.startup()
    server = ManagementAPI(runtime, ManagementConfig(TOKEN, port=unused_tcp_port), app_settings=store)
    await server.start()
    async with aiohttp.ClientSession(headers={"Authorization": "Bearer " + TOKEN}, trust_env=False) as client:
        async def call(path, payload=None, *, method=None, headers=None):
            async with client.request(method or ("POST" if payload is not None else "GET"),
                    f"http://127.0.0.1:{unused_tcp_port}" + path, json=payload, headers=headers) as response:
                return response.status, await response.json()
        yield server, call
    await server.close()
    await runtime.shutdown()


async def test_openai_saved_setup_and_playground_use_shared_policy_and_safe_usage(api, monkeypatch):
    from dataclasses import asdict
    from app.config.ai_setup import AISetup, AIModelSelection
    server, call = api
    assert (await call("/v1/credentials/replace", {"name": "openai_api_key", "value": "PRIVATE-OPENAI-KEY"}))[0] == 200
    setup = AISetup(AIModelSelection("openai", "gpt-6-luna", "none"))
    assert (await call("/v1/ai/setup", {"settings": asdict(setup)}))[0] == 200
    result = (await call("/v1/ai/setup"))[1]
    assert result["settings"]["primary"]["provider"] == "openai"
    assert result["capabilities"]["openai"]["gpt-6-luna"]["search_supported"]
    async def generate(method, path, key, **kwargs):
        assert key.get_secret_value() == "PRIVATE-OPENAI-KEY"
        assert kwargs["json"]["reasoning"] == {"effort": "none"}
        return 200, {"status": "completed", "model": "gpt-6-luna", "usage": {"input_tokens": 150, "output_tokens": 25},
                     "output": [{"type": "message", "role": "assistant", "status": "completed",
                                 "content": [{"type": "output_text", "text": "Friendly answer.", "annotations": []}]}]}
    monkeypatch.setattr(server.runtime.application.services.ai._providers["openai"], "_http_json", generate)
    status, started = await call("/v1/ai/playground/start", {"prompt": "Hello!"})
    assert status == 200
    await server.runtime.application.ai_playground.task
    status, answer = await call("/v1/ai/playground/result", {"request_id": started["request_id"]})
    assert status == 200 and answer["text"] == "Friendly answer."
    assert answer["generation"]["provider"] == "OpenAI"
    assert answer["generation"]["input_tokens"] == 150 and answer["generation"]["output_tokens"] == 25
    assert "PRIVATE" not in json.dumps(answer)


async def configure(call):
    assert (await call("/v1/twitch/settings", TWITCH))[0] == 200
    assert (await call("/v1/credentials/replace", {"name": "twitch_client_secret", "value": "synthetic-secret"}))[0] == 200


async def test_saved_channels_crud_does_not_apply_and_persists_after_reload(api):
    server, call = api
    await configure(call)
    before = server.runtime.application.settings.model_dump()
    payload = {"preset_id": None, "display_name": "Other channel", "channel": "other", "channel_user_id": "300"}
    status, result = await call("/v1/twitch/presets/save", payload)
    assert status == 200
    preset_id = result["preset_id"]
    assert server.runtime.application.settings.model_dump() == before
    stored = AppSettingsStore(RuntimePaths.default().app_settings).snapshot()
    assert stored.twitch.channel == "testchannel" and stored.startup.operation_mode == "manual"
    assert stored.twitch.presets[0].display_name == "Other channel"
    assert (await call("/v1/setup"))[1]["twitch"]["presets"][0]["id"] == preset_id
    assert (await call("/v1/twitch/presets/save", payload | {"display_name": "OTHER CHANNEL"}))[0] == 400
    for invalid in ({"channel": "bad login"}, {"channel": "x" * 26}, {"channel_user_id": "٣٠٠"}, {"display_name": ""}):
        assert (await call("/v1/twitch/presets/save", payload | invalid))[0] == 400
    assert (await call("/v1/twitch/presets/save", payload | {"preset_id": preset_id, "display_name": "Renamed"}))[0] == 200
    assert AppSettingsStore(RuntimePaths.default().app_settings).snapshot().twitch.presets[0].display_name == "Renamed"
    assert (await call("/v1/twitch/presets/delete", {"preset_id": preset_id}))[0] == 200
    assert not AppSettingsStore(RuntimePaths.default().app_settings).snapshot().twitch.presets
    assert server.runtime.application.settings.model_dump() == before
    assert (await call("/v1/twitch/presets/switch", {"preset_id": preset_id}))[0] == 400


@pytest.mark.parametrize("mode,running,resumes", [("manual", False, False), ("manual", True, True),
    ("always_on", True, True), ("stream_only", True, False), ("disabled", False, False)])
async def test_preset_switch_preserves_oauth_credentials_and_mode(api, monkeypatch, mode, running, resumes):
    from unittest.mock import AsyncMock
    server, call = api
    await configure(call)
    paths = RuntimePaths.default()
    paths.tokens.write_text('{"100":{"token":"synthetic-access","refresh":"synthetic-refresh"}}')
    credentials, tokens = (paths.auth / "server_credentials.json").read_bytes(), paths.tokens.read_bytes()
    payload = {"preset_id": None, "display_name": "Other", "channel": "other", "channel_user_id": "300"}
    preset_id = (await call("/v1/twitch/presets/save", payload))[1]["preset_id"]
    server.policy.store.update_operation_mode(mode)
    server.policy.mode, server.policy.desired_running = mode, running
    stopped = AsyncMock()
    monkeypatch.setattr(server.runtime, "stop_bot", stopped)
    monkeypatch.setattr(server.runtime, "start_bot", AsyncMock())
    status, result = await call("/v1/twitch/presets/switch", {"preset_id": preset_id})
    assert status == 200 and result["requires_reconnect"]
    stopped.assert_awaited()
    assert server.policy.mode == mode and server.policy.desired_running == resumes
    assert paths.tokens.read_bytes() == tokens
    assert (paths.auth / "server_credentials.json").read_bytes() == credentials
    settings = server.runtime.application.settings
    assert (settings.twitch_client_id, settings.twitch_bot_username, settings.twitch_bot_user_id) == ("test-client", "testbot", "100")
    assert (settings.twitch_channel, settings.twitch_channel_user_id) == ("other", "300")
    saved = AppSettingsStore(paths.app_settings).snapshot()
    assert saved.startup.operation_mode == mode and saved.twitch.channel == "other"
    setup = (await call("/v1/setup"))[1]["twitch"]
    assert setup["active_preset_id"] == preset_id and setup["oauth_token_available"]
    # Deleting the currently active preset must not disconnect or alter its target.
    stopped.reset_mock()
    assert (await call("/v1/twitch/presets/delete", {"preset_id": preset_id}))[0] == 200
    stopped.assert_not_awaited()
    assert settings.twitch_channel == "other" and paths.tokens.read_bytes() == tokens


async def test_failed_preset_write_keeps_active_target_and_authorization(api, monkeypatch):
    server, call = api
    await configure(call)
    before = server.setup.store.snapshot()
    def fail(*args, **kwargs):
        raise OSError("synthetic private path")
    monkeypatch.setattr("app.app_settings.save_app_settings", fail)
    assert (await call("/v1/twitch/presets/save", {"preset_id": None, "display_name": "Other",
        "channel": "other", "channel_user_id": "300"}))[0] == 500
    assert server.setup.store.snapshot() == before
    assert server.runtime.application.settings.twitch_channel == "testchannel"


@pytest.fixture
def twitch_provider(monkeypatch):
    outcome = {"client_id": "test-client", "user_id": "100", "login": "testbot",
               "scopes": list(CHAT_SCOPES.selected), "expires_in": 14400}
    requests = []
    async def exchange(self, code, *, redirect_uri):
        requests.append((code, redirect_uri))
        return UserTokenPayload({"access_token": "private-access-sentinel", "refresh_token": "private-refresh-sentinel",
            "expires_in": 14400, "scope": list(CHAT_SCOPES.selected), "token_type": "bearer"})
    async def add(bot, access, refresh):
        validated = ValidateTokenPayload(outcome)
        bot._http._tokens[validated.user_id] = {"user_id": validated.user_id, "token": access,
            "refresh": "rotated-" + refresh, "last_validated": "2026-10-20T00:00:00"}
        return validated
    async def users(bot, *, ids, token_for):
        assert set(ids) == {"100", "200"} and token_for == "100"
        return [SimpleNamespace(id="100", name="testbot"), SimpleNamespace(id="200", name="testchannel")]
    async def test_secret(client, url, **kwargs):
        assert url == "https://id.twitch.tv/oauth2/token"
        assert kwargs["data"]["grant_type"] == "client_credentials"
        return SimpleNamespace(status_code=200)
    monkeypatch.setattr("twitchio.authentication.oauth.OAuth.user_access_token", exchange)
    monkeypatch.setattr(TwitchChatBot, "add_token", add)
    monkeypatch.setattr(TwitchChatBot, "fetch_users", users)
    monkeypatch.setattr("httpx.AsyncClient.post", test_secret)
    return outcome, requests


async def begin(call):
    status, result = await call("/v1/twitch/authorization/begin", {})
    assert status == 200, result
    query = parse_qs(urlsplit(result["url"]).query)
    assert query["client_id"] == [TWITCH["client_id"]]
    redirect = (await call("/v1/setup"))[1]["twitch"]["oauth_callback_url"]
    assert query["redirect_uri"] == [redirect]
    assert redirect.startswith("http://localhost:") and redirect != OAUTH_REDIRECT_URI
    assert query["force_verify"] == ["true"]
    assert set(query["scope"][0].split()) == set(OAUTH_SCOPES.selected)
    return redirect + "?" + urlencode({"code": "private-code-sentinel", "state": query["state"][0]})


async def test_fresh_authenticated_setup_stays_available_in_every_mode(api):
    server, call = api
    assert (await call("/v1/setup", headers={"Authorization": ""}))[0] == 401
    status, result = await call("/v1/setup")
    assert status == 200 and not result["twitch"]["setup_complete"]
    assert result["twitch"]["authorization_status"] == "missing"
    assert all(not value["configured"] and value["managed"] for value in result["credentials"])
    for mode in ("always_on", "stream_only", "disabled", "manual"):
        assert (await call("/v1/bot/mode", {"mode": mode}))[0] == 200
        await asyncio.sleep(0.03)
        assert (await call("/v1/setup"))[0] == 200
        assert not server.runtime.bot_active
    assert (await call("/v1/bot/start", {}))[0] == 400
    assert (await call("/v1/twitch/authorization/begin", {}))[0] == 400


@pytest.mark.parametrize("path,payload", [
    ("/v1/twitch/settings", TWITCH),
    ("/v1/twitch/presets/save", {"preset_id": None, "display_name": "Channel", "channel": "other", "channel_user_id": "300"}),
    ("/v1/twitch/presets/delete", {"preset_id": "missing"}),
    ("/v1/twitch/presets/switch", {"preset_id": "missing"}),
    ("/v1/credentials/replace", {"name": "gemini_api_key", "value": "private-sentinel"}),
    ("/v1/credentials/remove", {"name": "gemini_api_key"}),
    ("/v1/credentials/test", {"name": "gemini_api_key"}),
    ("/v1/twitch/authorization/begin", {}),
    ("/v1/twitch/authorization/complete", {"callback_url": "private-sentinel"}),
    ("/v1/twitch/authorization/cancel", {}),
])
async def test_setup_mutations_require_auth_and_same_origin(api, path, payload):
    _, call = api
    assert (await call(path, payload, headers={"Authorization": ""}))[0] == 401
    assert (await call(path, payload, headers={"Origin": "https://evil.test"}))[0] == 403
    assert (await call(path, method="GET"))[0] == 404
    assert (await call(path, payload | {"extra": "private-sentinel"}))[0] == 400


async def test_credential_updates_persist_clear_validate_and_never_export(api, monkeypatch, caplog):
    server, call = api
    responses = await asyncio.gather(*[call("/v1/credentials/replace", {"name": name.value,
        "value": "private-" + name.value}) for name in CredentialName])
    assert all(status == 200 for status, _ in responses)
    manager = credential_manager(Settings())
    assert manager.effective_value(CredentialName.GEMINI_API_KEY) == "private-gemini_api_key"
    assert manager.effective_value(CredentialName.TWITCH_CLIENT_SECRET) == "private-twitch_client_secret"
    assert server.runtime.application.settings.gemini_api_key.get_secret_value() == "private-gemini_api_key"
    async def reject(url, **kwargs):
        assert "private-gemini_api_key" not in url
        assert kwargs["headers"]["x-goog-api-key"] == "private-gemini_api_key"
        return SimpleNamespace(status_code=401)
    monkeypatch.setattr(server.runtime.application.http_client, "get", reject)
    status, result = await call("/v1/credentials/test", {"name": "gemini_api_key"})
    assert status == 400 and "rejected" in result["error"]
    assert (await call("/v1/setup"))[1]["credentials"][1]["validation_status"] == "validation_failed"
    async def accept(*args, **kwargs):
        return SimpleNamespace(status_code=200)
    monkeypatch.setattr(server.runtime.application.http_client, "get", accept)
    assert (await call("/v1/credentials/test", {"name": "gemini_api_key"}))[0] == 200
    for path, payload in (("/v1/setup", None), ("/v1/diagnostics", None), ("/v1/ai/models", None),
                          ("/v1/configuration/export", {})):
        _, result = await call(path, payload)
        assert "private-gemini_api_key" not in json.dumps(result)
        assert "private-twitch_client_secret" not in json.dumps(result)
        if path.endswith("/export"):
            from app.configuration_transfer import unpack_configuration
            portable, _, _ = unpack_configuration(result["archive_base64"])
            assert "private-gemini_api_key" not in json.dumps(portable)
            assert "private-twitch_client_secret" not in json.dumps(portable)
    assert "private-gemini_api_key" not in caplog.text
    assert (await call("/v1/credentials/remove", {"name": "gemini_api_key"}))[0] == 200
    assert server.runtime.application.settings.gemini_api_key is None
    assert credential_manager(Settings()).effective_value(CredentialName.GEMINI_API_KEY) is None


@pytest.mark.parametrize("value", [None, 4, "", "x" * 8193, "line\nbreak", "key\x00secret", "ключ"])
async def test_invalid_credentials_are_bounded_and_do_not_mutate(api, value):
    server, call = api
    status, result = await call("/v1/credentials/replace", {"name": "gemini_api_key", "value": value})
    assert status == 400 and not server.setup.credentials.effective_value(CredentialName.GEMINI_API_KEY)
    assert "line\\nbreak" not in json.dumps(result)


@pytest.mark.parametrize("provider", ["gemini", "deepseek", "openai"])
async def test_external_secrets_cannot_be_shadowed_or_removed(api, provider):
    server, call = api
    manager = server.setup.credentials
    name = CredentialName(provider + "_api_key")
    manager._environment_fallbacks[name] = "external-sentinel"
    manager._store.replace(name, "dormant-browser-value")
    for path, payload in (("replace", {"name": name.value, "value": "browser-value"}),
                          ("remove", {"name": name.value})):
        status, result = await call("/v1/credentials/" + path, payload)
        assert status == 400 and "externally managed" in result["error"]
    assert manager.effective_value(name) == "external-sentinel"
    status = next(item for item in (await call("/v1/setup"))[1]["credentials"] if item["name"] == name)
    assert status["source"] == "environment" and not status["managed"]
    assert manager._store.get(name) == "dormant-browser-value"


@pytest.mark.parametrize("provider,url,model", [("deepseek", "https://api.deepseek.com/models", "deepseek-flash"),
                                              ("openai", "https://api.openai.com/v1/models", "gpt-6-luna")])
async def test_direct_backend_setup_discovery_rotation_and_removal(api, monkeypatch, caplog, provider, url, model):
    credential = provider + "_api_key"
    key_name = CredentialName(credential)
    custom, backup = provider + "-custom", provider + "-backup"
    import httpx
    from app.config.profile_settings import apply_ai_app_settings
    server, call = api
    settings = server.runtime.application.settings
    assert (await call("/v1/ai/models", {"provider": provider}))[0] == 200
    assert (await call("/v1/ai/models/discover", {"provider": provider}))[0] == 400
    for value in ("PRIVATE-FIRST-KEY", "PRIVATE-ROTATED-KEY"):
        assert (await call("/v1/credentials/replace", {"name": credential, "value": value}))[0] == 200
        assert getattr(settings, credential).get_secret_value() == value
        assert credential_manager(Settings()).effective_value(key_name) == value
    async def send(client, request, **kwargs):
        assert str(request.url) == url
        assert request.headers["Authorization"] == "Bearer PRIVATE-ROTATED-KEY"
        return httpx.Response(200, request=request, json={"data": [{"id": model}]})
    monkeypatch.setattr("httpx.AsyncClient.send", send)
    assert (await call("/v1/credentials/test", {"name": credential}))[0] == 200
    status, result = await call("/v1/ai/models/discover", {"provider": provider})
    assert status == 200 and result == {"ok": True, "models": [model], "provider_id": provider}
    assert (await call("/v1/ai/models", {"provider": provider, "selected_model": custom,
                                             "fallback_model": backup}))[0] == 200
    provider_info = (await call("/v1/ai/models"))[1]["settings"]
    assert provider_info["provider_id"] == provider and provider_info["selected_model"] == custom
    assert provider_info["credential"]["name"] == credential
    assert provider_info["credential"]["validation_status"] == "valid"
    assert (await call("/v1/setup"))[1]["aiProvider"]["credential"] == provider_info["credential"]
    async def reject(client, request, **kwargs):
        return httpx.Response(429, request=request, json={"error": {"message": "PRIVATE-KEY"}})
    monkeypatch.setattr("httpx.AsyncClient.send", reject)
    status, error = await call("/v1/ai/models/discover", {"provider": provider})
    assert status == 400 and error["error_code"] == "rate_limited"
    assert getattr(settings, provider + "_model") == custom and "PRIVATE" not in json.dumps(error)
    reloaded = apply_ai_app_settings(Settings(), AppSettingsStore(RuntimePaths.default().app_settings).snapshot())
    assert reloaded.ai_provider == provider and getattr(reloaded, provider + "_model") == custom
    assert (await call("/v1/ai/models", {"provider": provider, "selected_model": "gemini-wrong",
                                             "fallback_model": "gemini-also-wrong"}))[0] == 400
    assert getattr(settings, provider + "_model") == custom
    assert (await call("/v1/credentials/remove", {"name": credential}))[0] == 200
    assert getattr(settings, credential) is None
    assert credential_manager(Settings()).effective_value(key_name) is None
    assert not server.runtime.application.services.ai.is_available
    assert "PRIVATE" not in json.dumps(provider_info) + caplog.text


async def test_oauth_completion_works_disabled_and_replay_is_rejected(api, twitch_provider):
    server, call = api
    await configure(call)
    await call("/v1/bot/mode", {"mode": "disabled"})
    callback = await begin(call)
    assert (await call("/v1/twitch/authorization/complete", {"callback_url": callback}))[0] == 200
    assert twitch_provider[1] == [("private-code-sentinel", server.setup.redirect_uri)]
    setup = (await call("/v1/setup"))[1]["twitch"]
    assert setup["setup_complete"] and setup["authorized_account"] == "testbot"
    assert not server.runtime.bot_active and server.policy.mode == "disabled"
    assert "rotated-private-refresh-sentinel" in RuntimePaths.default().tokens.read_text()
    assert (await call("/v1/twitch/authorization/complete", {"callback_url": callback}))[0] == 400
    restarted = apply_twitch_app_settings(Settings(), AppSettingsStore(RuntimePaths.default().app_settings).snapshot())
    assert restarted.twitch_bot_username == "testbot" and restarted.twitch_channel == "testchannel"
    assert credential_manager(restarted).effective_value(CredentialName.TWITCH_CLIENT_SECRET) == "synthetic-secret"


@pytest.mark.parametrize("changes", [
    {"client_id": "wrong-app"}, {"user_id": "999"}, {"login": "wrongbot"}, {"scopes": ["user:read:chat"]},
])
async def test_wrong_application_account_or_scopes_never_persist(api, twitch_provider, changes):
    _, call = api
    await configure(call)
    callback = await begin(call)
    twitch_provider[0].update(changes)
    status, result = await call("/v1/twitch/authorization/complete", {"callback_url": callback})
    assert status == 400 and "private-access-sentinel" not in json.dumps(result)
    assert not RuntimePaths.default().tokens.exists()
    assert (await call("/v1/setup"))[1]["twitch"]["authorization_status"] == "validation_failed"


async def test_oauth_transactions_are_session_bound_cancelled_and_expiring(api, twitch_provider, monkeypatch):
    server, call = api
    await configure(call)
    session1 = (await call("/v1/session", {}))[1]["token"]
    session2 = (await call("/v1/session", {}))[1]["token"]
    first = {"Authorization": "Bearer " + session1}
    second = {"Authorization": "Bearer " + session2}
    status, result = await call("/v1/twitch/authorization/begin", {}, headers=first)
    assert status == 200
    state = parse_qs(urlsplit(result["url"]).query)["state"][0]
    callback = server.setup.redirect_uri + "?" + urlencode({"state": state, "code": "synthetic"})
    assert (await call("/v1/twitch/authorization/begin", {}, headers=second))[0] == 400
    assert (await call("/v1/twitch/authorization/complete", {"callback_url": callback}, headers=second))[0] == 400
    assert (await call("/v1/twitch/authorization/complete", {"callback_url": callback + "&state=duplicate"}, headers=first))[0] == 400
    assert (await call("/v1/session/logout", {}, headers=first))[0] == 200
    assert server.setup.pending is None
    callback = await begin(call)
    monkeypatch.setattr("app.server_setup.monotonic", lambda: server.setup.pending[2] + 1 if server.setup.pending else 0)
    assert (await call("/v1/twitch/authorization/complete", {"callback_url": callback}))[0] == 400
    assert not twitch_provider[1]


async def test_oauth_supersession_denial_cancellation_and_provider_failure(api, twitch_provider, monkeypatch):
    server, call = api
    await configure(call)
    old = await begin(call)
    current = await begin(call)
    assert (await call("/v1/twitch/authorization/complete", {"callback_url": old}))[0] == 400
    assert (await call("/v1/twitch/authorization/cancel", {}))[0] == 200
    assert (await call("/v1/twitch/authorization/complete", {"callback_url": current}))[0] == 400
    callback = await begin(call)
    denied = callback.replace("code=private-code-sentinel", "error=access_denied")
    status, result = await call("/v1/twitch/authorization/complete", {"callback_url": denied})
    assert status == 400 and "denied" in result["error"]
    callback = await begin(call)
    async def fail(*args, **kwargs):
        raise RuntimeError("private-code-sentinel private-access-sentinel")
    monkeypatch.setattr("twitchio.authentication.oauth.OAuth.user_access_token", fail)
    status, result = await call("/v1/twitch/authorization/complete", {"callback_url": callback})
    assert status == 400 and "private-code-sentinel" not in json.dumps(result)
    assert not server.setup.pending and not RuntimePaths.default().tokens.exists()


async def test_running_secret_change_waits_for_token_flush_and_blocks_concurrent_start(api, monkeypatch):
    server, call = api
    await configure(call)
    paths = RuntimePaths.default()
    paths.tokens.write_text('{"100":{"token":"synthetic","refresh":"synthetic"}}')
    started, closing, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    sessions = []
    async def session(**kwargs):
        sessions.append(True)
        started.set()
        await kwargs["stop_event"].wait()
        closing.set()
        await release.wait()
        # A late old-session flush must complete before invalidation/new settings.
        paths.tokens.write_text('{"100":{"token":"old","refresh":"final-old-rotation"}}')
    monkeypatch.setattr("app.bot_runtime.run_twitch_bot", session)
    assert (await call("/v1/bot/start", {}))[0] == 200
    await asyncio.wait_for(started.wait(), 1)
    change = asyncio.create_task(call("/v1/credentials/replace", {"name": "twitch_client_secret", "value": "new-synthetic-secret"}))
    try:
        await asyncio.wait_for(closing.wait(), 1)
        restart = asyncio.create_task(call("/v1/bot/start", {}))
        await asyncio.sleep(0.03)
        assert not change.done() and not restart.done()
        assert server.runtime.application.settings.twitch_client_secret.get_secret_value() == "synthetic-secret"
        release.set()
        assert (await change)[0] == 200 and (await restart)[0] == 400
        assert not paths.tokens.exists() and len(sessions) == 1
        assert server.runtime.application.settings.twitch_client_secret.get_secret_value() == "new-synthetic-secret"
        assert server.policy.mode == "manual"
    finally:
        release.set()
        await change


async def test_identity_change_failure_is_fail_closed_and_target_change_retains_tokens(api, monkeypatch):
    server, call = api
    await configure(call)
    path = RuntimePaths.default().tokens
    path.write_text('{"100":{"token":"synthetic","refresh":"synthetic"}}')
    assert (await call("/v1/twitch/settings", TWITCH | {"channel": "newchannel", "channel_user_id": "300"}))[0] == 200
    assert path.exists() and server.runtime.application.settings.twitch_channel == "newchannel"
    server.setup.authorization_status = "verified"
    server.policy.error = "connection_failed"
    assert not (await call("/v1/setup"))[1]["twitch"]["setup_complete"]
    def fail(**kwargs):
        raise OSError("private-application-sentinel")
    monkeypatch.setattr(server.setup.store, "update_twitch", fail)
    status, result = await call("/v1/twitch/settings", TWITCH | {"client_id": "replacement-app"})
    assert status == 500 and "private-application-sentinel" not in json.dumps(result)
    assert not path.exists()
    assert server.runtime.application.settings.twitch_client_id == "test-client"
    assert server.setup.store.snapshot().twitch.client_id == "test-client"


async def test_terminal_failed_session_can_be_reauthorized(api, twitch_provider, monkeypatch):
    server, call = api
    await configure(call)
    RuntimePaths.default().tokens.write_text('{"100":{"token":"synthetic","refresh":"synthetic"}}')
    async def failed_session(**kwargs):
        kwargs["services"].runtime_state.set_twitch_connection_state("auth_required")
        raise RuntimeError("private-old-provider-failure")
    monkeypatch.setattr("app.bot_runtime.run_twitch_bot", failed_session)
    assert (await call("/v1/bot/start", {}))[0] == 200
    await asyncio.sleep(0.03)
    assert not server.runtime.bot_active
    callback = await begin(call)
    assert (await call("/v1/twitch/authorization/complete", {"callback_url": callback}))[0] == 200
    assert (await call("/v1/setup"))[1]["twitch"]["setup_complete"]


@pytest.mark.parametrize("changes", [{"client_id": "wrong"}, {"scopes": []}, {"login": "wrong"}, {}])
async def test_headless_cached_tokens_verify_application_scopes_account_and_channel(api, twitch_provider, changes, monkeypatch):
    server, call = api
    await configure(call)
    twitch_provider[0].update(changes)
    path = RuntimePaths.default().tokens
    path.write_text('{"100":{"token":"synthetic","refresh":"synthetic"}}')
    bot = server.setup._bot()
    bot.require_verified_identity = True
    async def wrong_target(*args, **kwargs):
        return [SimpleNamespace(id="200", name="unexpected_channel")]
    monkeypatch.setattr(bot, "fetch_users", wrong_target)
    try:
        if changes:
            await bot.load_tokens()
            assert not bot.tokens  # Invalid cached account/application never activates.
            await bot.setup_hook()
            assert server.runtime.application.services.runtime_state.twitch_connection_state == "auth_required"
        else:
            from app.twitch.client import TwitchConnectionError
            with pytest.raises(TwitchConnectionError, match="channel"):
                await bot.load_tokens()
    finally:
        await bot.close(save_tokens=False)


def test_atomic_storage_failure_and_corruption_preserve_original(tmp_path, monkeypatch):
    path = tmp_path / "auth" / "server_credentials.json"
    store = ServerCredentialStore(path)
    store.replace(CredentialName.GEMINI_API_KEY, "original")
    before = path.read_bytes()
    def fail(*args):
        raise OSError("private-secret-sentinel")
    monkeypatch.setattr("app.server_credentials.os.replace", fail)
    with pytest.raises(CredentialError, match="Could not save"):
        store.replace(CredentialName.GEMINI_API_KEY, "replacement")
    assert path.read_bytes() == before and not list(path.parent.glob("*.tmp"))
    path.write_text('{"unknown":"private-sentinel"}')
    with pytest.raises(CredentialError):
        store.replace(CredentialName.GEMINI_API_KEY, "replacement")
    assert "private-sentinel" in path.read_text()


@pytest.mark.skipif(os.name != "posix", reason="Linux credential permission contract")
def test_private_file_modes_and_symlinks_are_rejected(tmp_path):
    path = tmp_path / "auth" / "server_credentials.json"
    store = ServerCredentialStore(path)
    store.replace(CredentialName.GEMINI_API_KEY, "synthetic")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    path.chmod(0o644)
    with pytest.raises(CredentialError):
        store.get(CredentialName.GEMINI_API_KEY)
    path.unlink()
    target = tmp_path / "other"
    target.write_text("unchanged")
    path.symlink_to(target)
    with pytest.raises(CredentialError):
        store.replace(CredentialName.GEMINI_API_KEY, "synthetic")
    assert target.read_text() == "unchanged"


REMOTE_ORIGIN = "https://server.example-tailnet.ts.net"
REMOTE_CALLBACK = REMOTE_ORIGIN + "/oauth/callback"


@pytest.fixture(params=["local", "docker", "https"])
async def callback_server(api, request):
    server, call = api
    port = server.config.port
    if request.param == "https":
        server.config = ManagementConfig(TOKEN, port=port, trusted_origin=REMOTE_ORIGIN,
            trusted_proxies=("127.0.0.1",), twitch_redirect_uri=REMOTE_CALLBACK)
        headers = {"Host": "server.example-tailnet.ts.net", "Origin": REMOTE_ORIGIN,
            "X-Forwarded-Proto": "https", "X-Forwarded-Host": "server.example-tailnet.ts.net"}
    else:
        if request.param == "docker":
            # Exercise the same all-interface bind/exact published Host contract
            # as Compose, without touching any Docker profile or credentials.
            server.config = ManagementConfig(TOKEN, host="0.0.0.0", port=port,
                allowed_host=f"127.0.0.1:{port}")
        headers = {"Host": f"127.0.0.1:{port}", "Origin": f"http://127.0.0.1:{port}"}
    server.setup.redirect_uri = server.config.oauth_redirect_uri
    api_headers = headers
    async def invoke(path, payload=None, *, headers=None):
        return await call(path, payload, headers=api_headers | (headers or {}))
    async def callback(query, *, method="GET", extra_headers=None):
        headers = api_headers | {"Host": urlsplit(server.setup.redirect_uri).netloc,
            "Sec-Fetch-Site": "cross-site"}
        headers.pop("Origin")  # Twitch's top-level GET redirect has no Origin.
        async with aiohttp.ClientSession(trust_env=False) as client:
            address = (f"http://127.0.0.1:{port}/oauth/callback" if server.config.trusted_origin
                       else server.setup.redirect_uri)
            async with client.request(method, address + "?" + query,
                    headers=headers | (extra_headers or {}), allow_redirects=False) as response:
                return response.status, await response.text(), response.headers
    yield server, invoke, callback


async def callback_begin(call, headers=None):
    status, result = await call("/v1/twitch/authorization/begin", {}, headers=headers)
    assert status == 200, result
    query = parse_qs(urlsplit(result["url"]).query)
    assert query["redirect_uri"] == [(await call("/v1/setup", headers=headers))[1]["twitch"]["oauth_callback_url"]]
    return urlencode({"code": "private-code-sentinel", "state": query["state"][0]})


async def test_callback_without_bearer_persists_and_scrubs_parameters(callback_server, twitch_provider, caplog):
    server, call, callback = callback_server
    await configure(call)
    await call("/v1/bot/mode", {"mode": "disabled"})
    first = {"Authorization": "Bearer " + (await call("/v1/session", {}))[1]["token"]}
    second = {"Authorization": "Bearer " + (await call("/v1/session", {}))[1]["token"]}
    query = await callback_begin(call, first)
    assert (await call("/v1/twitch/authorization/begin", {}, headers=second))[0] == 400
    assert (await call("/v1/setup", headers=second))[1]["twitch"]["authorization_attempt"] == "idle"
    status, body, headers = await callback(query)
    assert status == 303 and headers["Location"] == "/oauth/result"
    assert headers["Cache-Control"] == "no-store" and headers["Referrer-Policy"] == "no-referrer"
    assert "Set-Cookie" not in headers and "Access-Control-Allow-Origin" not in headers
    # Browsers retain cross-site Fetch Metadata through a redirect chain. The
    # clean result is public inert text, never a session or callback projection.
    async with aiohttp.ClientSession(trust_env=False) as browser:
        async with browser.get(f"http://127.0.0.1:{server.config.port}/oauth/result", headers={
                "Host": urlsplit(server.setup.redirect_uri).netloc,
                **({"X-Forwarded-Proto": "https"} if server.config.trusted_origin else {}),
                "Sec-Fetch-Site": "cross-site"}) as result_page:
            assert result_page.status == 200
            assert "return to the signed-in Settings tab" in await result_page.text()
    assert twitch_provider[1] == [("private-code-sentinel", server.setup.redirect_uri)]
    assert RuntimePaths.default().tokens.is_file()
    assert not server.runtime.bot_active
    result = (await call("/v1/setup", headers=first))[1]["twitch"]
    assert result["authorization_attempt"] == "completed" and result["authorized_account"] == "testbot"
    assert result["management_url"] == (server.config.trusted_origin or f"http://127.0.0.1:{server.config.port}")
    assert result["oauth_callback_url"] == server.setup.redirect_uri
    assert result["authorization_mode"] == "redirect"
    # Replay and concurrent duplicate navigation cannot perform a second exchange.
    await asyncio.gather(callback(query), callback(query))
    assert len(twitch_provider[1]) == 1
    for sentinel in ("private-code-sentinel", "private-access-sentinel", "private-refresh-sentinel", TOKEN,
                     parse_qs(query)["state"][0]):
        assert sentinel not in body + str(headers) + caplog.text + json.dumps(result)


@pytest.mark.parametrize("change", [
    "state=wrong&code=private-code-sentinel", "code=private-code-sentinel", "state=wrong&state=twice",
    "state=%FF&code=private-code-sentinel", "state=wrong&unexpected=secret",
])
async def test_unsolicited_callback_never_consumes_valid_attempt(callback_server, twitch_provider, change):
    server, call, callback = callback_server
    await configure(call)
    query = await callback_begin(call)
    assert (await callback(change))[0] == 303
    assert not twitch_provider[1] and server.setup.pending is not None
    await callback(query)
    assert len(twitch_provider[1]) == 1


@pytest.mark.parametrize("reason", ["cancel", "logout", "expiry", "session_expiry", "session_eviction", "superseded", "identity"])
async def test_callback_cannot_outlive_administrator_attempt(callback_server, twitch_provider, monkeypatch, reason):
    server, call, callback = callback_server
    await configure(call)
    session = (await call("/v1/session", {}))[1]["token"]
    headers = {"Authorization": "Bearer " + session}
    query = await callback_begin(call, headers)
    if reason == "cancel":
        await call("/v1/twitch/authorization/cancel", {}, headers=headers)
    elif reason == "logout":
        await call("/v1/session/logout", {}, headers=headers)
    elif reason == "expiry":
        deadline = server.setup.pending[2]
        monkeypatch.setattr("app.server_setup.monotonic", lambda: deadline + 1)
    elif reason == "session_expiry":
        server.sessions[next(iter(server.sessions))] = 0
    elif reason == "session_eviction":
        for _ in range(8):
            await call("/v1/session", {})
    elif reason == "superseded":
        await callback_begin(call, headers)
    else:
        await call("/v1/twitch/settings", TWITCH | {"bot_username": "otherbot"})
    await callback(query)
    assert not twitch_provider[1] and not RuntimePaths.default().tokens.exists()


@pytest.mark.parametrize("failure", ["denied", "provider", "account", "app", "scopes", "target", "late_session", "storage"])
async def test_callback_denial_provider_failure_and_identity_substitution_never_persist(callback_server, twitch_provider, monkeypatch, caplog, failure):
    server, call, callback = callback_server
    await configure(call)
    session = (await call("/v1/session", {}))[1]["token"]
    headers = {"Authorization": "Bearer " + session}
    query = await callback_begin(call, headers)
    if failure == "denied":
        query = query.replace("code=private-code-sentinel", "error=access_denied&error_description=private-code-sentinel")
    elif failure == "provider":
        async def fail(*args, **kwargs):
            raise RuntimeError("private-code-sentinel private-access-sentinel private-refresh-sentinel")
        monkeypatch.setattr("twitchio.authentication.oauth.OAuth.user_access_token", fail)
    elif failure in ("account", "app", "scopes"):
        twitch_provider[0].update({"account": {"user_id": "999"}, "app": {"client_id": "wrong"},
                                  "scopes": {"scopes": []}}[failure])
    elif failure == "target":
        async def users(*args, **kwargs):
            return [SimpleNamespace(id="100", name="testbot"), SimpleNamespace(id="200", name="other")]
        monkeypatch.setattr(TwitchChatBot, "fetch_users", users)
    elif failure == "storage":
        def fail(*args, **kwargs):
            raise OSError("private-refresh-sentinel")
        monkeypatch.setattr("app.twitch.client.os.replace", fail)
    else:
        original = TwitchChatBot.fetch_users
        async def expire(*args, **kwargs):
            server.sessions.clear()
            return await original(*args, **kwargs)
        monkeypatch.setattr(TwitchChatBot, "fetch_users", expire)
    status, body, response_headers = await callback(query)
    assert status == 303 and not RuntimePaths.default().tokens.exists()
    assert server.setup.attempt_status(__import__("hashlib").sha256(session.encode()).digest()) == "failed"
    assert not server.setup.pending and not server.policy._setup_suspended
    assert not list(RuntimePaths.default().auth.glob("*.tmp"))
    # Even failed/denied callbacks consume state and cannot retry an exchange.
    exchanges = len(twitch_provider[1])
    await callback(query)
    assert len(twitch_provider[1]) == exchanges
    for value in ("private-code-sentinel", "private-access-sentinel", "private-refresh-sentinel"):
        assert value not in caplog.text + body + str(response_headers)


async def test_callback_is_only_cross_site_exception_and_is_get_only(callback_server, twitch_provider):
    _, call, callback = callback_server
    await configure(call)
    query = await callback_begin(call)
    assert (await callback(query, method="POST"))[0] == 400
    assert (await callback(query, extra_headers={"Origin": "https://evil.test"}))[0] == 403
    assert (await call("/v1/twitch/authorization/begin", {}, headers={"Sec-Fetch-Site": "cross-site"}))[0] == 403
    assert not twitch_provider[1]
    await callback(query)
    assert len(twitch_provider[1]) == 1


async def test_authorization_expires_without_browser_polling(api, twitch_provider, monkeypatch):
    server, call = api
    await configure(call)
    monkeypatch.setattr("app.server_setup.OAUTH_STATE_TTL_SECONDS", 0.05)
    await begin(call)
    await asyncio.sleep(0.1)
    assert server.setup.pending is None and not server.policy._setup_suspended
    assert server.setup.outcome[1] == "expired" and not twitch_provider[1]


async def test_concurrent_callbacks_consume_state_before_exchange(callback_server, twitch_provider, monkeypatch):
    _, call, callback = callback_server
    await configure(call)
    query = await callback_begin(call)
    entered, release = asyncio.Event(), asyncio.Event()
    from twitchio.authentication.oauth import OAuth
    original = OAuth.user_access_token
    async def exchange(*args, **kwargs):
        entered.set()
        await release.wait()
        return await original(*args, **kwargs)
    monkeypatch.setattr(OAuth, "user_access_token", exchange)
    first = asyncio.create_task(callback(query))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        duplicate = asyncio.create_task(callback(query))
        release.set()
        assert all(result[0] == 303 for result in await asyncio.gather(first, duplicate))
        assert len(twitch_provider[1]) == 1
    finally:
        release.set()
        await first


@pytest.mark.parametrize("change", ["desktop_port", "ip_host", "external_origin", "trailing_slash"])
async def test_paste_completion_requires_exact_server_redirect(api, twitch_provider, change):
    server, call = api
    await configure(call)
    callback = await begin(call)
    replacement = {
        "desktop_port": OAUTH_REDIRECT_URI,
        "ip_host": server.setup.redirect_uri.replace("localhost", "127.0.0.1"),
        "external_origin": "https://evil.test/oauth/callback",
        "trailing_slash": server.setup.redirect_uri + "/",
    }[change]
    wrong = replacement + "?" + urlsplit(callback).query
    assert (await call("/v1/twitch/authorization/complete", {"callback_url": wrong}))[0] == 400
    assert not twitch_provider[1] and server.setup.pending is not None
    assert (await call("/v1/twitch/authorization/complete", {"callback_url": callback}))[0] == 200


async def test_callback_uses_only_fixed_host_and_retains_management_security(callback_server, twitch_provider):
    server, call, callback = callback_server
    await configure(call)
    query = await callback_begin(call)
    host = urlsplit(server.setup.redirect_uri).netloc
    for value in ("evil.test", host + ".evil.test", "localhost:4343"):
        assert (await callback(query, extra_headers={"Host": value}))[0] == 403
    for duplicate in ("&state=duplicate", "&code=duplicate"):
        assert (await callback(query + duplicate))[0] == 303
    if not server.config.trusted_origin:
        assert (await callback(query, extra_headers={"X-Forwarded-Proto": "https"}))[0] == 403
    if server.config.allowed_host:
        assert (await call("/v1/setup", headers={"Host": host, "Origin": "http://" + host}))[0] == 403
        assert (await call("/", headers={"Host": host, "Origin": "http://" + host}))[0] == 403
    assert (await call("/v1/setup", headers={"Authorization": ""}))[0] == 401
    assert (await call("/v1/setup", headers={"Sec-Fetch-Site": "cross-site"}))[0] == 403
    assert not twitch_provider[1] and server.setup.pending is not None
    await callback(query)
    assert len(twitch_provider[1]) == 1


async def test_callback_tokens_reload_through_existing_cache(callback_server, twitch_provider):
    server, call, callback = callback_server
    await configure(call)
    await callback(await callback_begin(call))
    saved = json.loads(RuntimePaths.default().tokens.read_text())
    assert saved["100"]["refresh"] == "rotated-private-refresh-sentinel"
    bot = server.setup._bot()
    try:
        await bot.load_tokens()
        assert bot.tokens["100"]["token"] == saved["100"]["token"]
        assert bot.tokens["100"]["refresh"] == "rotated-" + saved["100"]["refresh"]
    finally:
        await bot.close(save_tokens=False)
    assert json.loads(RuntimePaths.default().tokens.read_text())["100"]["refresh"] == "rotated-" + saved["100"]["refresh"]


async def test_alternate_loopback_retains_authenticated_paste_completion(api, twitch_provider):
    server, original_call = api
    port = server.config.port
    server.config = ManagementConfig(TOKEN, host="0.0.0.0", port=port, allowed_host=f"127.0.0.2:{port}")
    async def call(path, payload=None):
        return await original_call(path, payload, headers={"Host": f"127.0.0.2:{port}",
            "Origin": f"http://127.0.0.2:{port}"})
    await configure(call)
    result = (await call("/v1/setup"))[1]["twitch"]
    assert result["authorization_mode"] == "paste"
    assert result["oauth_callback_url"] == f"http://localhost:{port}/oauth/callback"
    callback = await begin(call)
    async with aiohttp.ClientSession(trust_env=False) as browser:
        async with browser.get(callback, allow_redirects=False) as response:
            assert response.status == 403
    assert not twitch_provider[1] and server.setup.pending is not None
    assert (await call("/v1/twitch/authorization/complete", {"callback_url": callback}))[0] == 200


@pytest.fixture
async def twitch_http(api, monkeypatch, unused_tcp_port_factory):
    """Real TwitchIO HTTP/OAuth/token/model code; only the wire is redirected.

    The mock refuses missing/wrong Authorization just as Helix does. No token
    registration, user lookup, save or cleanup method is replaced.
    """
    port = unused_tcp_port_factory()
    provider = SimpleNamespace(calls=[], validation={"client_id": TWITCH["client_id"],
        "user_id": "100", "login": "testbot", "scopes": list(CHAT_SCOPES.selected),
        "expires_in": 14400}, failure=None, refresh=False, target="testchannel", clients=[], writes=[],
        pause=None, entered=asyncio.Event(), lookup_expired=False)
    server, _ = api
    original_bot = server.setup._bot
    def create_bot():
        bot = original_bot()
        provider.clients.append(bot)
        return bot
    monkeypatch.setattr(server.setup, "_bot", create_bot)
    original_replace = os.replace
    def replace(source, target):
        if str(target) == str(RuntimePaths.default().tokens):
            provider.writes.append(True)
            if provider.failure == "token_persistence":
                raise OSError("private-provider-body-sentinel")
        return original_replace(source, target)
    monkeypatch.setattr("app.twitch.client.os.replace", replace)
    async def token(request):
        grant = request.query["grant_type"]
        stage = "code_exchange" if grant == "authorization_code" else "token_refresh"
        provider.calls.append(stage)
        assert request.query["client_id"] == TWITCH["client_id"]
        assert request.query["client_secret"] == "synthetic-secret"
        if stage == "code_exchange":
            assert request.query["code"] == "private-code-sentinel"
            assert request.query["redirect_uri"] == server.setup.redirect_uri
        else:
            assert grant == "refresh_token" and request.query["refresh_token"] == "private-refresh-sentinel"
        if provider.failure == stage:
            return web.json_response({"message": "private-provider-body-sentinel"}, status=400)
        prefix = "rotated-" if stage == "token_refresh" else ""
        return web.json_response({"access_token": prefix + "private-access-sentinel",
            "refresh_token": prefix + "private-refresh-sentinel", "expires_in": 14400,
            "scope": list(CHAT_SCOPES.selected), "token_type": "bearer"})
    async def validate(request):
        provider.calls.append("token_validate")
        assert request.headers["Authorization"] in ("OAuth private-access-sentinel", "OAuth rotated-private-access-sentinel")
        if provider.failure == "token_validate":
            return web.json_response({"message": "private-provider-body-sentinel"}, status=403)
        payload = provider.validation.copy()
        if provider.refresh and request.headers["Authorization"] == "OAuth private-access-sentinel":
            payload["expires_in"] = 60
        return web.json_response(payload)
    async def users(request):
        provider.calls.append("user_lookup")
        expected = "Bearer " + ("rotated-" if provider.refresh else "") + "private-access-sentinel"
        if request.headers.get("Authorization") != expected:
            provider.calls.append("user_lookup_unauthorized")
            return web.json_response({"message": "OAuth token is missing"}, status=401)
        if provider.lookup_expired and not provider.refresh:
            provider.refresh = True
            return web.json_response({"message": "Invalid OAuth token"}, status=401)
        if provider.failure == "user_lookup":
            return web.json_response({"message": "private-provider-body-sentinel"}, status=403)
        if provider.pause is not None:
            provider.entered.set()
            await provider.pause.wait()
        return web.json_response({"data": [{"id": uid, "login": login, "display_name": login,
            "type": "", "broadcaster_type": "", "description": "", "profile_image_url": "https://example.test/avatar.png",
            "offline_image_url": "", "created_at": "2026-01-01T00:00:00Z"}
            for uid, login in (("100", "testbot"), ("200", provider.target))
            if uid in request.query.getall("id", [])]})
    application = web.Application()
    application.router.add_post("/oauth2/token", token)
    application.router.add_get("/oauth2/validate", validate)
    application.router.add_get("/helix/users", users)
    runner = web.AppRunner(application, access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", port).start()
    original = aiohttp.ClientSession._request
    async def request(session, method, address, **kwargs):
        url = URL(address)
        if url.host in ("id.twitch.tv", "api.twitch.tv"):
            url = url.with_scheme("http").with_host("127.0.0.1").with_port(port)
        else:
            assert url.host in ("127.0.0.1", "localhost"), "External HTTP is forbidden"
        return await original(session, method, url, **kwargs)
    async def test_secret(*args, **kwargs):
        return SimpleNamespace(status_code=200)
    monkeypatch.setattr(HTTPClient, "request", TWITCH_HTTP_REQUEST)
    monkeypatch.setattr(aiohttp.ClientSession, "_request", request)
    monkeypatch.setattr("httpx.AsyncClient.post", test_secret)
    try:
        yield provider
    finally:
        await runner.cleanup()


def assert_setup_clients_closed(provider):
    for bot in provider.clients:
        assert bot._has_closed and not bot.tokens
        assert bot.http._app_token is None
        assert bot.http._validate_task is None and not bot.http._session_set
        assert not bot.http._ManagedHTTPClient__isolated._session_set


@pytest.mark.parametrize("refresh", ["none", "registration", "lookup"])
@pytest.mark.parametrize("completion", ["paste", "callback"])
async def test_real_twitchio_oauth_completion(callback_server, twitch_http, refresh, completion, caplog):
    server, call, callback = callback_server
    twitch_http.refresh = refresh == "registration"
    twitch_http.lookup_expired = refresh == "lookup"
    await configure(call)
    query = await callback_begin(call)
    if completion == "paste":
        status, result = await call("/v1/twitch/authorization/complete",
            {"callback_url": server.setup.redirect_uri + "?" + query})
        assert status == 200, (result, twitch_http.calls)
    else:
        status, result, headers = await callback(query)
        assert status == 303 and headers["Location"] == "/oauth/result"
    expected = ["code_exchange", "token_validate"]
    if refresh == "registration":
        expected += ["token_refresh", "token_validate"]
    expected += ["user_lookup"]
    if refresh == "lookup":
        expected += ["token_refresh", "user_lookup"]
    assert twitch_http.calls == expected
    saved = json.loads(RuntimePaths.default().tokens.read_text())
    prefix = "rotated-" if refresh != "none" else ""
    assert saved["100"]["token"] == prefix + "private-access-sentinel"
    assert saved["100"]["refresh"] == prefix + "private-refresh-sentinel"
    assert len(twitch_http.writes) == 1
    assert server.setup.authorization_status == "verified"
    assert not server.policy._setup_suspended and server.setup.pending is None
    assert server.runtime.application.services.runtime_state.twitch_connection_state == "stopped"
    assert_setup_clients_closed(twitch_http)
    assert "Server Twitch OAuth failed" not in caplog.text
    # Normal cache loading still uses real token validation and atomic writes.
    reloaded = server.setup._bot()
    try:
        await reloaded.load_tokens()
        assert reloaded.tokens["100"]["refresh"] == saved["100"]["refresh"]
    finally:
        await reloaded.close(save_tokens=False)
    assert_setup_clients_closed(twitch_http)


@pytest.mark.parametrize("failure,operation,exception,status", [
    ("code_exchange", "code_exchange", "HTTPException", 400),
    ("token_validate", "token_registration", "InvalidTokenException", 403),
    ("token_refresh", "token_registration", "InvalidTokenException", 400),
    ("application", "account_verification", "TwitchConnectionError", "none"),
    ("account", "account_verification", "TwitchConnectionError", "none"),
    ("login", "account_verification", "TwitchConnectionError", "none"),
    ("scopes", "account_verification", "TwitchConnectionError", "none"),
    ("target", "target_verification", "CredentialError", "none"),
    ("user_lookup", "user_lookup", "HTTPException", 403),
    ("token_persistence", "token_persistence", "TwitchConnectionError", "none"),
])
async def test_real_twitchio_failures_are_safe_single_use_and_close_clients(api, twitch_http,
        caplog, failure, operation, exception, status):
    server, call = api
    await configure(call)
    callback = await begin(call)
    twitch_http.failure = failure
    if failure == "token_refresh":
        twitch_http.refresh = True
    elif failure in ("application", "account", "login", "scopes"):
        twitch_http.validation.update({"application": {"client_id": "wrong"}, "account": {"user_id": "999"},
            "login": {"login": "wrong"}, "scopes": {"scopes": []}}[failure])
    elif failure == "target":
        twitch_http.target = "wrong"
    status_code, result = await call("/v1/twitch/authorization/complete", {"callback_url": callback})
    assert status_code == 400
    assert f"operation={operation} exception={exception} http_status={status}" in caplog.text
    assert server.setup.authorization_status == "validation_failed" and server.setup.outcome[1] == "failed"
    assert not server.policy._setup_suspended and server.setup.pending is None
    assert not RuntimePaths.default().tokens.exists() and not list(RuntimePaths.default().auth.glob("*.tmp"))
    assert len(twitch_http.writes) == (1 if failure == "token_persistence" else 0)
    assert_setup_clients_closed(twitch_http)
    previous_calls = twitch_http.calls.copy()
    assert (await call("/v1/twitch/authorization/complete", {"callback_url": callback}))[0] == 400
    assert twitch_http.calls == previous_calls
    for value in ("private-code-sentinel", "private-access-sentinel", "private-refresh-sentinel",
            "private-provider-body-sentinel", "synthetic-secret", parse_qs(urlsplit(callback).query)["state"][0]):
        assert value not in caplog.text + json.dumps(result)


async def test_real_twitchio_cancellation_closes_clients_without_persisting(api, twitch_http, caplog):
    server, call = api
    await configure(call)
    callback = await begin(call)
    twitch_http.pause = asyncio.Event()
    owner = __import__("hashlib").sha256(TOKEN.encode()).digest()
    task = asyncio.create_task(server.setup.complete(owner, callback))
    try:
        await asyncio.wait_for(twitch_http.entered.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        twitch_http.pause.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert "operation=user_lookup exception=CancelledError http_status=none" in caplog.text
    assert not server.policy._setup_suspended and server.setup.pending is None
    assert not RuntimePaths.default().tokens.exists() and not twitch_http.writes
    assert_setup_clients_closed(twitch_http)


@pytest.mark.parametrize("lookup_fails", [False, True])
async def test_real_twitchio_cleanup_failure_does_not_mask_primary_failure(api, twitch_http,
        caplog, monkeypatch, lookup_fails):
    from twitchio.authentication.tokens import ManagedHTTPClient
    server, call = api
    await configure(call)
    callback = await begin(call)
    if lookup_fails:
        twitch_http.failure = "user_lookup"
    cleanup = ManagedHTTPClient.cleanup
    def fail_after_cleanup(client):
        cleanup(client)
        raise RuntimeError("private-provider-body-sentinel")
    monkeypatch.setattr(ManagedHTTPClient, "cleanup", fail_after_cleanup)
    status, result = await call("/v1/twitch/authorization/complete", {"callback_url": callback})
    assert status == 400
    assert "operation=client_cleanup exception=RuntimeError http_status=none" in caplog.text
    if lookup_fails:
        assert "operation=user_lookup exception=HTTPException http_status=403" in caplog.text
        assert "user_lookup" in result["error"]
    else:
        assert "client_cleanup" in result["error"]
    assert RuntimePaths.default().tokens.exists() is not lookup_fails
    assert server.setup.outcome[1] == "failed" and not server.policy._setup_suspended
    assert_setup_clients_closed(twitch_http)
    assert "private-provider-body-sentinel" not in caplog.text + json.dumps(result)


async def test_real_twitchio_runtime_reconciliation_failure_is_not_reported_completed(api,
        twitch_http, caplog, monkeypatch):
    server, call = api
    await configure(call)
    callback = await begin(call)
    def fail(*args):
        raise RuntimeError("private-provider-body-sentinel")
    monkeypatch.setattr(server.runtime.application.services.runtime_state, "set_twitch_connection_state", fail)
    status, _ = await call("/v1/twitch/authorization/complete", {"callback_url": callback})
    assert status == 400 and server.setup.outcome[1] == "failed"
    assert server.setup.authorization_status == "validation_failed"
    assert "operation=runtime_reconciliation exception=RuntimeError http_status=none" in caplog.text
    assert RuntimePaths.default().tokens.exists()  # Preserve valid committed authorization.
    assert not server.policy._setup_suspended
    assert_setup_clients_closed(twitch_http)
    assert "private-provider-body-sentinel" not in caplog.text


@pytest.mark.parametrize("status,expected", [(400, "400"), (True, "none"), (999, "none"),
    ("private-provider-body-sentinel", "none")])
def test_oauth_diagnostics_survive_headless_filter_without_rendering_exception(caplog, status, expected):
    from twitchio.exceptions import HTTPException
    from app.headless import HeadlessLogFilter
    from app.server_setup import _oauth_failure
    error = HTTPException("private-provider-body-sentinel", status=status,
        extra={"message": "private-access-sentinel"})
    _oauth_failure("code_exchange", error)
    record = next(record for record in caplog.records if record.name == "app.headless")
    assert HeadlessLogFilter().filter(record)
    assert record.getMessage() == f"Server Twitch OAuth failed operation=code_exchange exception=HTTPException http_status={expected}"
    assert record.exc_info is None
    assert "private-provider-body-sentinel" not in caplog.text and "private-access-sentinel" not in caplog.text
