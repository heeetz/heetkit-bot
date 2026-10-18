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
    return settings.model_copy(update=overrides)


def apply_ai_app_settings(settings: Settings, app_settings: AppSettings) -> Settings:
    ai = app_settings.ai
    overrides = {"ai_response_language": ai.response_language}
    if ai.selected_model is not None and ai.fallback_model is not None:
        overrides.update(gemini_model=ai.selected_model, gemini_fallback_model=ai.fallback_model)
    if ai.cooldown_bypass_user_id is not None:
        overrides["ai_cooldown_bypass_user_id"] = ai.cooldown_bypass_user_id
    return settings.model_copy(update=overrides) if overrides else settings
