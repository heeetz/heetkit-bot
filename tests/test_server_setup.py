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
from twitchio.authentication.payloads import UserTokenPayload, ValidateTokenPayload

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
from app.twitch.client import CHAT_SCOPES, OAUTH_REDIRECT_URI, TwitchChatBot


TOKEN = "synthetic_management_token_" + "x" * 32
TWITCH = {"client_id": "test-client", "bot_username": "testbot", "bot_user_id": "100",
          "channel": "testchannel", "channel_user_id": "200"}


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


async def configure(call):
    assert (await call("/v1/twitch/settings", TWITCH))[0] == 200
    assert (await call("/v1/credentials/replace", {"name": "twitch_client_secret", "value": "synthetic-secret"}))[0] == 200


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
    assert query["redirect_uri"] == [OAUTH_REDIRECT_URI]
    assert query["force_verify"] == ["true"]
    assert set(query["scope"][0].split()) == set(CHAT_SCOPES.selected)
    return OAUTH_REDIRECT_URI + "?" + urlencode({"code": "private-code-sentinel", "state": query["state"][0]})


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


async def test_external_secrets_cannot_be_shadowed_or_removed(api):
    server, call = api
    manager = server.setup.credentials
    manager._environment_fallbacks[CredentialName.GEMINI_API_KEY] = "external-sentinel"
    manager._store.replace(CredentialName.GEMINI_API_KEY, "dormant-browser-value")
    for path, payload in (("replace", {"name": "gemini_api_key", "value": "browser-value"}),
                          ("remove", {"name": "gemini_api_key"})):
        status, result = await call("/v1/credentials/" + path, payload)
        assert status == 400 and "externally managed" in result["error"]
    assert manager.effective_value(CredentialName.GEMINI_API_KEY) == "external-sentinel"
    status = (await call("/v1/setup"))[1]["credentials"][1]
    assert status["source"] == "environment" and not status["managed"]
    assert manager._store.get(CredentialName.GEMINI_API_KEY) == "dormant-browser-value"


async def test_oauth_completion_works_disabled_and_replay_is_rejected(api, twitch_provider):
    server, call = api
    await configure(call)
    await call("/v1/bot/mode", {"mode": "disabled"})
    callback = await begin(call)
    assert (await call("/v1/twitch/authorization/complete", {"callback_url": callback}))[0] == 200
    assert twitch_provider[1] == [("private-code-sentinel", OAUTH_REDIRECT_URI)]
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
    callback = OAUTH_REDIRECT_URI + "?" + urlencode({"state": state, "code": "synthetic"})
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
