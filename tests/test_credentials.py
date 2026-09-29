"""Focused tests for OS-backed credential storage and bridge operations."""

from __future__ import annotations

import asyncio
from concurrent.futures import Future
from types import SimpleNamespace
from typing import cast

import httpx
import pytest
from keyring.errors import KeyringError, PasswordDeleteError

from app.credentials import (
    CREDENTIAL_SERVICE_NAME,
    CredentialManager,
    CredentialName,
    CredentialStore,
)
from app.webview_host import AsyncioBackendHost, WebUIBridge


class FakeKeyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}
        self.available = True

    def get_password(self, service_name: str, username: str) -> str | None:
        if not self.available:
            raise KeyringError("unavailable")
        return self.values.get((service_name, username))

    def set_password(self, service_name: str, username: str, password: str) -> None:
        if not self.available:
            raise KeyringError("unavailable")
        self.values[(service_name, username)] = password

    def delete_password(self, service_name: str, username: str) -> None:
        try:
            del self.values[(service_name, username)]
        except KeyError as error:
            raise PasswordDeleteError("missing") from error


class FakeHTTPClient:
    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code
        self.requests: list[tuple[str, str, dict[str, object]]] = []

    async def get(self, url: str, **kwargs) -> SimpleNamespace:
        self.requests.append(("GET", url, kwargs))
        return SimpleNamespace(status_code=self.status_code)

    async def post(self, url: str, **kwargs) -> SimpleNamespace:
        self.requests.append(("POST", url, kwargs))
        return SimpleNamespace(status_code=self.status_code)


def build_manager(backend: FakeKeyring) -> CredentialManager:
    return CredentialManager(
        {
            CredentialName.GEMINI_API_KEY: "env-gemini",
            CredentialName.TWITCH_CLIENT_SECRET: "env-twitch",
        },
        store=CredentialStore(backend),
    )


def test_secure_credentials_override_environment_without_exposing_values() -> None:
    backend = FakeKeyring()
    backend.values[(CREDENTIAL_SERVICE_NAME, "gemini_api_key")] = "secure-gemini"
    manager = build_manager(backend)

    assert manager.settings_overrides() == {
        "gemini_api_key": "secure-gemini",
        "twitch_client_secret": "env-twitch",
    }
    serialized = [status.serialize() for status in manager.statuses()]
    assert serialized[0]["source"] == "credential_store"
    assert serialized[1]["source"] == "environment"
    assert "secure-gemini" not in repr(serialized)
    assert "env-twitch" not in repr(serialized)


def test_replace_and_remove_use_only_the_os_credential_store() -> None:
    backend = FakeKeyring()
    manager = build_manager(backend)

    manager.replace("gemini_api_key", "  replacement  ")

    assert backend.values[(CREDENTIAL_SERVICE_NAME, "gemini_api_key")] == "replacement"
    assert manager.remove("gemini_api_key") is True
    assert manager.remove("gemini_api_key") is False


def test_unavailable_secure_store_falls_back_to_environment(caplog) -> None:
    backend = FakeKeyring()
    backend.available = False
    manager = build_manager(backend)

    with caplog.at_level("WARNING"):
        assert manager.effective_value(CredentialName.GEMINI_API_KEY) == "env-gemini"
        status = manager.statuses()[0]

    assert status.source == "environment"
    assert status.secure_storage_available is False
    assert "env-gemini" not in caplog.text


@pytest.mark.asyncio
async def test_provider_tests_do_not_put_gemini_secret_in_the_url() -> None:
    backend = FakeKeyring()
    manager = build_manager(backend)
    http_client = FakeHTTPClient()

    await manager.test(
        "gemini_api_key",
        http_client=cast(httpx.AsyncClient, http_client),
        twitch_client_id="client-id",
    )
    await manager.test(
        "twitch_client_secret",
        http_client=cast(httpx.AsyncClient, http_client),
        twitch_client_id="client-id",
    )

    gemini_request, twitch_request = http_client.requests
    assert "env-gemini" not in gemini_request[1]
    assert gemini_request[2]["headers"] == {"x-goog-api-key": "env-gemini"}
    assert twitch_request[2]["data"] == {
        "client_id": "client-id",
        "client_secret": "env-twitch",
        "grant_type": "client_credentials",
    }


class ImmediateBackend:
    def __init__(self, http_client: FakeHTTPClient) -> None:
        self.application = SimpleNamespace(
            http_client=http_client,
            settings=SimpleNamespace(twitch_client_id="client-id"),
        )

    def submit(self, coroutine) -> Future[object]:
        future: Future[object] = Future()
        try:
            future.set_result(asyncio.run(coroutine))
        except Exception as error:
            future.set_exception(error)
        return future


def test_bridge_exposes_status_and_actions_without_secret_values() -> None:
    backend = FakeKeyring()
    manager = build_manager(backend)
    bridge = WebUIBridge(
        cast(AsyncioBackendHost, ImmediateBackend(FakeHTTPClient())),
        credential_manager=manager,
    )

    status = bridge.get_credentials()
    assert status["ok"] is True
    assert "env-gemini" not in repr(status)
    assert bridge.replace_credential("gemini_api_key", "secure") == {"ok": True}
    assert bridge.test_credential("gemini_api_key") == {"ok": True}
    assert bridge.remove_credential("gemini_api_key") == {
        "ok": True,
        "changed": True,
    }


def test_bridge_does_not_log_secret_when_secure_storage_fails(caplog) -> None:
    backend = FakeKeyring()
    backend.available = False
    bridge = WebUIBridge(
        cast(AsyncioBackendHost, ImmediateBackend(FakeHTTPClient())),
        credential_manager=build_manager(backend),
    )

    with caplog.at_level("WARNING"):
        result = bridge.replace_credential("gemini_api_key", "never-log-this")

    assert result == {
        "ok": False,
        "error": "Could not store the credential securely.",
    }
    assert "never-log-this" not in caplog.text
