"""Shared setup behavior with synthetic profiles and injected host boundaries."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from app.app_settings import AppSettingsStore
from app.config.settings import Settings
from app.credentials import CredentialManager, CredentialName
from app.server_credentials import ServerCredentialManager, ServerCredentialStore
from app.twitch_setup import DesktopOAuth, ServerOAuth, TwitchSetup


@pytest.fixture(params=["desktop", "server"])
def setup(request, tmp_path):
    settings = Settings(_env_file=None, twitch_client_id="test-client",
        twitch_bot_username="testbot", twitch_bot_user_id="100",
        twitch_channel="testchannel", twitch_channel_user_id="200",
        twitch_client_secret="synthetic-old-secret", twitch_token_file=str(tmp_path / "tokens.json"))
    store = AppSettingsStore(tmp_path / "settings.json")
    store.update_twitch(client_id="test-client", bot_username="testbot", bot_user_id="100",
        channel="testchannel", channel_user_id="200")
    # Inject a private synthetic store for both managers; never discover a keyring.
    secrets = ServerCredentialStore(tmp_path / "auth" / "credentials.json")
    secrets.replace(CredentialName.TWITCH_CLIENT_SECRET, "synthetic-old-secret")
    manager = (ServerCredentialManager if request.param == "server" else CredentialManager)({}, secrets)
    policy = SimpleNamespace(suspend_for_setup=AsyncMock(), resume_after_setup=Mock(), desired_running=False)
    runtime = SimpleNamespace(application=SimpleNamespace(settings=settings))
    oauth = (ServerOAuth(redirect_uri="http://localhost:4343/oauth/callback")
        if request.param == "server" else DesktopOAuth(
            wait=lambda coroutine, **kwargs: asyncio.run(coroutine), timeout_error=TimeoutError,
            settings_timeout=10, credential_timeout=15, reconnect_timeout=30))
    import logging
    return request.param, TwitchSetup(runtime, policy, store, manager,
        oauth=oauth, logger=logging.getLogger(__name__))


def test_target_only_save_preserves_bot_authorization(setup):
    host, service = setup
    service.token_path.write_bytes(b"synthetic-bot-authorization")
    if host == "server":
        result = asyncio.run(service.save_twitch(client_id="test-client", bot_username="testbot",
            bot_user_id="100", channel="otherchannel", channel_user_id="300"))
    else:
        result = service.desktop_update_twitch_settings("otherchannel", "300")
    assert result["ok"] and result["requires_reconnect"]
    assert service.token_path.read_bytes() == b"synthetic-bot-authorization"
    assert service.store.snapshot().twitch.channel == "otherchannel"
    assert not service.requires_restart(service.store.snapshot().twitch)


def test_secret_change_preserves_host_apply_timing_and_uses_shared_probe(setup):
    host, service = setup
    service.token_path.write_bytes(b"synthetic-bot-authorization")
    if host == "server":
        result = asyncio.run(service.change_credential("twitch_client_secret", "synthetic-new-secret"))
        assert result["requires_reconnect"] and not service.token_path.exists()
        assert service.settings.twitch_client_secret.get_secret_value() == "synthetic-new-secret"
    else:
        result = service.desktop_replace_credential("twitch_client_secret", "synthetic-new-secret")
        assert result["requires_restart"] and service.token_path.is_file()
        assert service.settings.twitch_client_secret.get_secret_value() == "synthetic-old-secret"
    assert result["ok"] and result["changed"]
    assert "synthetic-new-secret" not in json.dumps(result)

    requests = []

    def probe(request):
        requests.append(request)
        return httpx.Response(200)

    async def verify():
        async with httpx.AsyncClient(transport=httpx.MockTransport(probe)) as client:
            service.runtime.application.http_client = client
            return await service.test_credential("twitch_client_secret")

    assert asyncio.run(verify()) == {"ok": True}
    assert len(requests) == 1
    assert b"client_secret=synthetic-new-secret" in requests[0].content
