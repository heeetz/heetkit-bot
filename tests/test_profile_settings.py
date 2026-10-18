"""Saved profile settings overlay runtime configuration without desktop imports."""

from pydantic import SecretStr

from app.app_settings import AISettings, AppSettings, TwitchSettings
from app.config.ai_language import ResponseLanguageSettings
from app.config.profile_settings import apply_ai_app_settings, apply_twitch_app_settings
from app.config.settings import Settings


def test_saved_twitch_and_ai_settings_take_precedence() -> None:
    runtime = Settings(
        _env_file=None,
        twitch_client_id="environment-client",
        twitch_client_secret=SecretStr("environment-secret"),
        twitch_bot_username="environment-bot",
        twitch_bot_user_id="100",
        twitch_channel="environment-channel",
        twitch_channel_user_id="200",
        gemini_api_key=SecretStr("environment-ai-key"),
        gemini_model="gemini-environment",
        gemini_fallback_model="gemini-environment-fallback",
        ai_cooldown_bypass_user_id="300",
    )
    language = ResponseLanguageSettings("limited", ("en", "uk"), "en")
    saved = AppSettings(
        twitch=TwitchSettings(
            client_id="saved-client",
            bot_username="saved-bot",
            bot_user_id="400",
            channel="saved-channel",
            channel_user_id="500",
        ),
        ai=AISettings(
            selected_model="gemini-saved",
            fallback_model="gemini-saved-fallback",
            cooldown_bypass_user_id="600",
            response_language=language,
        ),
    )

    effective = apply_ai_app_settings(apply_twitch_app_settings(runtime, saved), saved)

    assert (
        effective.twitch_client_id,
        effective.twitch_bot_username,
        effective.twitch_bot_user_id,
        effective.twitch_channel,
        effective.twitch_channel_user_id,
    ) == ("saved-client", "saved-bot", "400", "saved-channel", "500")
    assert (effective.gemini_model, effective.gemini_fallback_model) == (
        "gemini-saved",
        "gemini-saved-fallback",
    )
    assert effective.ai_cooldown_bypass_user_id == "600"
    assert effective.ai_response_language == language
    assert effective.twitch_client_secret == runtime.twitch_client_secret
    assert effective.gemini_api_key == runtime.gemini_api_key
    assert runtime.twitch_client_id == "environment-client"
    assert runtime.gemini_model == "gemini-environment"


def test_missing_saved_values_preserve_environment_and_runtime_defaults() -> None:
    runtime = Settings(
        _env_file=None,
        twitch_client_id="environment-client",
        twitch_bot_username="environment-bot",
        twitch_channel="environment-channel",
        gemini_model="gemini-environment",
        gemini_fallback_model="gemini-environment-fallback",
        ai_cooldown_bypass_user_id="300",
    )

    effective = apply_ai_app_settings(
        apply_twitch_app_settings(runtime, AppSettings()),
        AppSettings(),
    )

    assert effective.twitch_client_id == "environment-client"
    assert effective.twitch_bot_username == "environment-bot"
    assert effective.twitch_channel == "environment-channel"
    assert effective.twitch_bot_user_id == runtime.twitch_bot_user_id == ""
    assert effective.twitch_channel_user_id == runtime.twitch_channel_user_id == ""
    assert effective.gemini_model == "gemini-environment"
    assert effective.gemini_fallback_model == "gemini-environment-fallback"
    assert effective.ai_cooldown_bypass_user_id == "300"
    assert effective.ai_response_language == runtime.ai_response_language
