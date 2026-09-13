"""Typed configuration loaded from the environment."""

from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    twitch_token_file: str = "data/twitchio_tokens.json"
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-3.5-flash-lite"
    ai_cooldown_bypass_user_id: str | None = None
    database_url: str = "sqlite+aiosqlite:///./data/twitch_bot.db"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    command_prefix: str = "!"
    command_max_arguments_length: int = Field(default=300, ge=1, le=450)

    @field_validator("command_prefix")
    @classmethod
    def validate_command_prefix(cls, value: str) -> str:
        if not value or value.isspace():
            raise ValueError("COMMAND_PREFIX must contain at least one visible character.")
        return value

    @property
    def primary_account(self) -> TwitchAccountSettings:
        return TwitchAccountSettings(
            user_id=self.twitch_bot_user_id,
            username=self.twitch_bot_username,
            channel_user_id=self.twitch_channel_user_id,
            channel=self.twitch_channel,
        )


def load_settings() -> Settings:
    settings = Settings()
    print("BOT:", settings.twitch_bot_username)
    print("CHANNEL:", settings.twitch_channel)
    print("CHANNEL ID:", settings.twitch_channel_user_id)
    print("TOKEN FILE:", settings.twitch_token_file)
    return settings
