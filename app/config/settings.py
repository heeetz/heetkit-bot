"""Typed runtime defaults and intentional process environment overrides.

Normal startup never reads dotenv files. Desktop settings overlay non-secret
defaults in the host; credentials come from the profile's OS keyring first.
"""

from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config.ai_models import (
    DEFAULT_GEMINI_FALLBACK_MODEL,
    validate_gemini_model_id,
)
from app.config.ai_language import ResponseLanguageSettings, validate_response_language
from app.credentials import CredentialManager, CredentialName, CredentialStore
from app.runtime_paths import RuntimePaths


class TwitchConfigurationError(ValueError):
    """Safe setup error with field names only, never credential values."""


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
        env_file=None,
        env_prefix="",
        extra="ignore",
    )

    twitch_client_id: str = ""
    twitch_client_secret: SecretStr | None = None
    twitch_bot_user_id: str = ""
    twitch_bot_username: str = ""
    twitch_channel_user_id: str = ""
    twitch_channel: str = ""
    twitch_token_file: str = Field(default_factory=lambda: str(RuntimePaths.default().tokens))
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_fallback_model: str = DEFAULT_GEMINI_FALLBACK_MODEL
    ai_cooldown_bypass_user_id: str | None = None
    ai_response_language: ResponseLanguageSettings = Field(default_factory=ResponseLanguageSettings)
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

    @field_validator("ai_response_language")
    @classmethod
    def validate_ai_response_language(cls, value: ResponseLanguageSettings) -> ResponseLanguageSettings:
        return validate_response_language(value.mode, value.allowed_languages, value.fallback_language)

    @field_validator("twitch_client_secret")
    @classmethod
    def normalize_twitch_secret(cls, value: SecretStr | None) -> SecretStr | None:
        return value if value is not None and value.get_secret_value().strip() else None

    def validate_twitch_configuration(self) -> None:
        """Require complete Twitch setup only when a connection is requested."""
        missing = [
            name.upper()
            for name in (
                "twitch_client_id", "twitch_bot_user_id", "twitch_bot_username",
                "twitch_channel_user_id", "twitch_channel",
            )
            if not getattr(self, name).strip()
        ]
        if self.twitch_client_secret is None or not self.twitch_client_secret.get_secret_value().strip():
            missing.append("TWITCH_CLIENT_SECRET")
        if missing:
            raise TwitchConfigurationError(
                "Configure Twitch before starting the bot. Missing: " + ", ".join(missing) + "."
            )

    @property
    def primary_account(self) -> TwitchAccountSettings:
        return TwitchAccountSettings(
            user_id=self.twitch_bot_user_id,
            username=self.twitch_bot_username,
            channel_user_id=self.twitch_channel_user_id,
            channel=self.twitch_channel,
        )


class EnvironmentCredentialSettings(BaseSettings):
    """Advanced process environment fallbacks for OS-backed credentials."""

    model_config = SettingsConfigDict(
        env_file=None,
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
) -> tuple[Settings, CredentialManager]:
    paths = RuntimePaths.default()
    environment = EnvironmentCredentialSettings()
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
    settings = Settings(**overrides)
    return settings, manager


def load_settings() -> Settings:
    settings, _ = load_settings_with_credentials()
    return settings
