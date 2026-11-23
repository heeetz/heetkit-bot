"""Apply saved profile settings to runtime configuration."""

from app.app_settings import AIModelPair, AppSettings, CustomAIConnection
from app.config.settings import Settings


def apply_twitch_app_settings(settings: Settings, app_settings: AppSettings) -> Settings:
    twitch = app_settings.twitch
    overrides = {
        f"twitch_{name}": value
        for name in ("client_id", "bot_username", "bot_user_id", "channel", "channel_user_id")
        if (value := getattr(twitch, name)) is not None
    }
    return settings.model_copy(update=overrides)


def apply_ai_app_settings(settings: Settings, app_settings: AppSettings, *, allow_custom: bool = False) -> Settings:
    """Only Desktop passes ``allow_custom``: v1 sends nothing to a custom endpoint from Server."""
    ai = app_settings.ai
    overrides = {"ai_response_language": ai.response_language, "ai_setup": ai.setup,
                 "ai_history_max_entries": ai.history_max_entries, "ai_context_max_entries": ai.context_max_entries}
    if ai.provider is not None:
        overrides["ai_provider"] = ai.provider
    for provider, models in ai.providers.items():
        if isinstance(models, AIModelPair):
            overrides.update({provider + "_model": models.selected_model,
                              provider + "_fallback_model": models.fallback_model})
    custom = ai.providers.get("custom")
    if allow_custom and isinstance(custom, CustomAIConnection):
        overrides["custom_base_url"] = custom.base_url
    if ai.cooldown_bypass_user_id is not None:
        overrides["ai_cooldown_bypass_user_id"] = ai.cooldown_bypass_user_id
    if ai.setup is not None:
        overrides["ai_provider"] = ai.setup.primary.provider
    return settings.model_copy(update=overrides) if overrides else settings
