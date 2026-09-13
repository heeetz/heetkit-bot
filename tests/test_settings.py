"""Tests for typed environment configuration."""

import pytest
from pydantic import ValidationError

from app.config.settings import Settings


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
    assert settings.twitch_token_file == "data/twitchio_tokens.json"


def test_settings_require_twitch_identity() -> None:
    values = valid_settings()
    del values["twitch_client_id"]

    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)