"""Tests for typed environment configuration."""

import pytest
from pydantic import ValidationError

from app.config.settings import Settings, load_settings_with_credentials
from app.credentials import CREDENTIAL_SERVICE_NAME, CredentialStore
from app.runtime_paths import RuntimePaths


class FakeKeyring:
    def __init__(self, values: dict[tuple[str, str], str]) -> None:
        self.values = values

    def get_password(self, service_name: str, username: str) -> str | None:
        return self.values.get((service_name, username))

    def set_password(self, service_name: str, username: str, password: str) -> None:
        self.values[(service_name, username)] = password

    def delete_password(self, service_name: str, username: str) -> None:
        del self.values[(service_name, username)]


def valid_settings() -> dict[str, str]:
    return {
        "twitch_client_id": "client-id",
        "twitch_client_secret": "client-secret",
        "twitch_bot_user_id": "100",
        "twitch_bot_username": "testbot",
        "twitch_channel_user_id": "200",
        "twitch_channel": "testchannel",
    }


def test_settings_create_primary_account() -> None:
    settings = Settings(_env_file=None, **valid_settings())

    assert settings.primary_account.username == "testbot"
    assert settings.twitch_token_file == str(RuntimePaths.default().tokens)
    assert settings.database_url.endswith(str(RuntimePaths.default().database))
    assert settings.gemini_model == "gemini-3.5-flash-lite"
    assert settings.gemini_fallback_model == "gemini-3.1-flash-lite"


def test_settings_require_twitch_identity() -> None:
    values = valid_settings()
    del values["twitch_client_id"]

    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)


def test_secure_credentials_override_environment_fallbacks(monkeypatch) -> None:
    for name, value in valid_settings().items():
        monkeypatch.setenv(name.upper(), value)
    monkeypatch.setenv("GEMINI_API_KEY", "environment-gemini")
    backend = FakeKeyring(
        {
            (CREDENTIAL_SERVICE_NAME, "twitch_client_secret"): "secure-twitch",
            (CREDENTIAL_SERVICE_NAME, "gemini_api_key"): "secure-gemini",
        }
    )

    settings, _ = load_settings_with_credentials(
        CredentialStore(backend),
        env_file=None,
    )

    assert settings.twitch_client_secret.get_secret_value() == "secure-twitch"
    assert settings.gemini_api_key is not None
    assert settings.gemini_api_key.get_secret_value() == "secure-gemini"


def test_empty_optional_environment_credential_is_treated_as_missing(monkeypatch) -> None:
    for name, value in valid_settings().items():
        monkeypatch.setenv(name.upper(), value)
    monkeypatch.setenv("GEMINI_API_KEY", "")

    settings, manager = load_settings_with_credentials(
        CredentialStore(FakeKeyring({})),
        env_file=None,
    )

    assert settings.gemini_api_key is None
    gemini_status = manager.statuses()[0]
    assert gemini_status.configured is False
    assert gemini_status.source == "missing"
