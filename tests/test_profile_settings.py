"""Saved profile settings overlay runtime configuration without desktop imports."""

from pydantic import SecretStr

from app.app_settings import AIModelPair, AISettings, AppSettings, CustomAIConnection, TwitchSettings
from app.config.ai_language import ResponseLanguageSettings
from app.config.profile_settings import apply_ai_app_settings, apply_twitch_app_settings
from app.config.settings import Settings


def test_unsaved_provider_default_and_explicit_saved_selection():
    settings = Settings(ai_provider="deepseek")
    assert apply_ai_app_settings(settings, AppSettings()).ai_provider == "deepseek"
    assert apply_ai_app_settings(settings, AppSettings(ai=AISettings(provider="gemini"))).ai_provider == "gemini"


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
            providers={"gemini": AIModelPair("gemini-saved", "gemini-saved-fallback"),
                       "custom": CustomAIConnection("http://localhost:1234/v1")},
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
    # Server applies the same profile without its custom endpoint (Desktop only in v1).
    assert effective.custom_base_url is None
    assert apply_ai_app_settings(runtime, saved, allow_custom=True).custom_base_url == "http://localhost:1234/v1"
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
