"""Typed runtime defaults and intentional process environment overrides.

Normal startup never reads dotenv files. Desktop settings overlay non-secret
defaults in the host; credentials come from the profile's OS keyring first.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config.ai_models import (
    DEFAULT_GEMINI_FALLBACK_MODEL,
    DEFAULT_DEEPSEEK_MODEL, DEFAULT_DEEPSEEK_FALLBACK_MODEL, validate_provider_model_id,
    DEFAULT_OPENAI_MODEL, DEFAULT_OPENAI_FALLBACK_MODEL,
)
from app.config.ai_language import ResponseLanguageSettings, validate_response_language
from app.config.ai_setup import AISetup
from app.config.privacy import AI_HISTORY_MAX_ENTRIES, AI_CONTEXT_MAX_ENTRIES, validate_memory_limits
from app.runtime_paths import RuntimePaths

if TYPE_CHECKING:
    from app.credentials import CredentialManager, CredentialStore


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
    ai_provider: Literal["gemini", "deepseek", "openai"] = "gemini"
    deepseek_api_key: SecretStr | None = None
    deepseek_model: str = DEFAULT_DEEPSEEK_MODEL
    deepseek_fallback_model: str = DEFAULT_DEEPSEEK_FALLBACK_MODEL
    openai_api_key: SecretStr | None = None
    openai_model: str = DEFAULT_OPENAI_MODEL
    openai_fallback_model: str = DEFAULT_OPENAI_FALLBACK_MODEL
    ai_cooldown_bypass_user_id: str | None = None
    ai_response_language: ResponseLanguageSettings = Field(default_factory=ResponseLanguageSettings)
    ai_setup: AISetup | None = None
    ai_history_max_entries: int = Field(default=AI_HISTORY_MAX_ENTRIES, strict=True, ge=1, le=500)
    ai_context_max_entries: int = Field(default=AI_CONTEXT_MAX_ENTRIES, strict=True, ge=1, le=50)
    database_url: str = Field(
        default_factory=lambda: "sqlite+aiosqlite:///" + str(RuntimePaths.default().database)
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    command_prefix: str = "!"
    command_max_arguments_length: int = Field(default=300, ge=1, le=450)

    @model_validator(mode="after")
    def validate_memory_policy(self):
        validate_memory_limits(self.ai_history_max_entries, self.ai_context_max_entries)
        return self

    @field_validator("command_prefix")
    @classmethod
    def validate_command_prefix(cls, value: str) -> str:
        if not value or value.isspace():
            raise ValueError("COMMAND_PREFIX must contain at least one visible character.")
        return value

    @field_validator("gemini_model", "gemini_fallback_model")
    @classmethod
    def validate_gemini_model(cls, value: str) -> str:
        return validate_provider_model_id("gemini", value)

    @field_validator("deepseek_model", "deepseek_fallback_model")
    @classmethod
    def validate_deepseek_model(cls, value: str) -> str:
        # Validate the namespace without imposing a static discovery allowlist.
        return validate_provider_model_id("deepseek", value)

    @field_validator("openai_model", "openai_fallback_model")
    @classmethod
    def validate_openai_model(cls, value: str) -> str:
        return validate_provider_model_id("openai", value)

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
    deepseek_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None


def _read_environment_secret(value: SecretStr | None) -> str | None:
    if value is None:
        return None
    normalized = value.get_secret_value().strip()
    return normalized or None


def load_settings_with_credentials(
    credential_store: CredentialStore | None = None,
) -> tuple[Settings, CredentialManager]:
    from app.credentials import CredentialManager, CredentialName

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
            CredentialName.DEEPSEEK_API_KEY: _read_environment_secret(environment.deepseek_api_key),
            CredentialName.OPENAI_API_KEY: _read_environment_secret(environment.openai_api_key),
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
