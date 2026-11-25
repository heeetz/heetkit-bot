"""Apply saved profile settings to runtime configuration."""

from app.app_settings import AppSettings
from app.config.settings import Settings


def apply_twitch_app_settings(settings: Settings, app_settings: AppSettings) -> Settings:
    twitch = app_settings.twitch
    overrides = {
        f"twitch_{name}": value
        for name in ("client_id", "bot_username", "bot_user_id", "channel", "channel_user_id")
        if (value := getattr(twitch, name)) is not None
    }
    overrides["reply_interval_seconds"] = app_settings.chat.reply_interval_seconds
    return settings.model_copy(update=overrides)


def apply_ai_app_settings(settings: Settings, app_settings: AppSettings) -> Settings:
    ai = app_settings.ai
    overrides = {"ai_response_language": ai.response_language, "ai_setup": ai.setup,
                 "ai_history_max_entries": ai.history_max_entries, "ai_context_max_entries": ai.context_max_entries}
    if ai.provider is not None:
        overrides["ai_provider"] = ai.provider
    for provider, models in ai.providers.items():
        overrides.update({provider + "_model": models.selected_model,
                          provider + "_fallback_model": models.fallback_model})
    overrides["ai_connections"] = ai.connections
    if ai.cooldown_bypass_user_id is not None:
        overrides["ai_cooldown_bypass_user_id"] = ai.cooldown_bypass_user_id
    if ai.setup is not None:
        overrides["ai_provider"] = ai.setup.primary.provider
    return settings.model_copy(update=overrides) if overrides else settings


def load_ai_connection_keys(settings: Settings, credentials) -> None:
    """Load keys of connections after the first of each type (the first loads with the fixed credentials)."""
    from pydantic import SecretStr
    from app.config.ai_models import provider_type
    keys = {}
    for connection in settings.ai_connections:
        if connection.id != provider_type(connection.id):
            value = credentials.effective_value(credentials.ai_key_name(connection.id))
            if value:
                keys[connection.id] = SecretStr(value)
    settings.ai_keys = keys
