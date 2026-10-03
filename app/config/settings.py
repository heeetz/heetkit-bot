"""Typed configuration loaded from the environment."""

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config.ai_models import (
    DEFAULT_GEMINI_FALLBACK_MODEL,
    validate_gemini_model_id,
)
from app.credentials import CredentialManager, CredentialName, CredentialStore
from app.runtime_paths import RuntimePaths


class TwitchAccountSettings(BaseSettings):
    """Identity and channel information for one bot account."""

    model_config = SettingsConfigDict(extra="ignore")

    user_id: str
    username: str
    channel_user_id: str
    channel: str


class Settings(BaseSettings):
    """Runtime settings for the primary bot process."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="",
        extra="ignore",
    )

    twitch_client_id: str
    twitch_client_secret: SecretStr
    twitch_bot_user_id: str
    twitch_bot_username: str
    twitch_channel_user_id: str
    twitch_channel: str
    twitch_token_file: str = Field(default_factory=lambda: str(RuntimePaths.default().tokens))
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_fallback_model: str = DEFAULT_GEMINI_FALLBACK_MODEL
    ai_cooldown_bypass_user_id: str | None = None
    database_url: str = Field(
        default_factory=lambda: "sqlite+aiosqlite:///" + str(RuntimePaths.default().database)
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    command_prefix: str = "!"
    command_max_arguments_length: int = Field(default=300, ge=1, le=450)

    @field_validator("command_prefix")
    @classmethod
    def validate_command_prefix(cls, value: str) -> str:
        if not value or value.isspace():
            raise ValueError("COMMAND_PREFIX must contain at least one visible character.")
        return value

    @field_validator("gemini_model", "gemini_fallback_model")
    @classmethod
    def validate_gemini_model(cls, value: str) -> str:
        return validate_gemini_model_id(value)

    @property
    def primary_account(self) -> TwitchAccountSettings:
        return TwitchAccountSettings(
            user_id=self.twitch_bot_user_id,
            username=self.twitch_bot_username,
            channel_user_id=self.twitch_channel_user_id,
            channel=self.twitch_channel,
        )


class EnvironmentCredentialSettings(BaseSettings):
    """Private `.env`/environment fallbacks for OS-backed credentials."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="",
        extra="ignore",
    )

    twitch_client_secret: SecretStr | None = None
    gemini_api_key: SecretStr | None = None


def _read_environment_secret(value: SecretStr | None) -> str | None:
    if value is None:
        return None
    normalized = value.get_secret_value().strip()
    return normalized or None


def load_settings_with_credentials(
    credential_store: CredentialStore | None = None,
    *,
    env_file: str | Path | None = ".env",
) -> tuple[Settings, CredentialManager]:
    paths = RuntimePaths.default()
    if env_file == ".env" and not paths.is_default_profile:
        env_file = paths.root / ".env"
    environment = EnvironmentCredentialSettings(_env_file=env_file)
    manager = CredentialManager(
        {
            CredentialName.TWITCH_CLIENT_SECRET: _read_environment_secret(
                environment.twitch_client_secret
            ),
            CredentialName.GEMINI_API_KEY: _read_environment_secret(
                environment.gemini_api_key
            ),
        },
        store=credential_store,
    )
    overrides = manager.settings_overrides()
    if not paths.is_default_profile:
        overrides.update(twitch_token_file=str(paths.tokens), database_url="sqlite+aiosqlite:///" + str(paths.database))
    settings = Settings(_env_file=env_file, **overrides)
    return settings, manager


def load_settings() -> Settings:
    settings, _ = load_settings_with_credentials()
    return settings
