"""User-editable, non-secret bot behavior settings."""

from pathlib import Path

from app.config.personalities import AI_PERSONALITY_PRESETS


PROJECT_ROOT = Path(__file__).resolve().parent
FILTERS_DIRECTORY = PROJECT_ROOT / "data" / "filters"


# Command behavior.
TG_BURST_DELAY = 0.01
TG_MESSAGE = "t.me/sch1lla <- 🍑🍑🍑"
PING_COOLDOWN_SECONDS = 10.0
HELP_COOLDOWN_SECONDS = 10.0
COMMANDS_COOLDOWN_SECONDS = 15.0
UPTIME_COOLDOWN_SECONDS = 15.0
FORECAST_COOLDOWN_SECONDS = 15.0
WEATHER_COOLDOWN_SECONDS = 15.0
FOLLOWAGE_COOLDOWN_SECONDS = 10.0
SEEN_COOLDOWN_SECONDS = 15.0
ASK_COOLDOWN_SECONDS = 25.0


# AI behavior. API keys remain in .env.
AI_MAX_RESPONSE_LENGTH = 220
AI_MEMORY_ENABLED = True
AI_MEMORY_MAX_ENTRIES = 5
ACTIVE_AI_PERSONALITY = "vas2"



def _validate_behavior_settings() -> None:
    if AI_MAX_RESPONSE_LENGTH <= 0:
        raise ValueError("AI_MAX_RESPONSE_LENGTH must be greater than zero.")
    if AI_MEMORY_MAX_ENTRIES < 1:
        raise ValueError("AI_MEMORY_MAX_ENTRIES must be at least one.")
    for name, value in (
        ("TG_BURST_DELAY", TG_BURST_DELAY),
        ("PING_COOLDOWN_SECONDS", PING_COOLDOWN_SECONDS),
        ("HELP_COOLDOWN_SECONDS", HELP_COOLDOWN_SECONDS),
        ("COMMANDS_COOLDOWN_SECONDS", COMMANDS_COOLDOWN_SECONDS),
        ("UPTIME_COOLDOWN_SECONDS", UPTIME_COOLDOWN_SECONDS),
        ("FORECAST_COOLDOWN_SECONDS", FORECAST_COOLDOWN_SECONDS),
        ("WEATHER_COOLDOWN_SECONDS", WEATHER_COOLDOWN_SECONDS),
        ("FOLLOWAGE_COOLDOWN_SECONDS", FOLLOWAGE_COOLDOWN_SECONDS),
        ("SEEN_COOLDOWN_SECONDS", SEEN_COOLDOWN_SECONDS),
        ("ASK_COOLDOWN_SECONDS", ASK_COOLDOWN_SECONDS),
    ):
        if value < 0:
            raise ValueError(f"{name} must not be negative.")
    if ACTIVE_AI_PERSONALITY not in AI_PERSONALITY_PRESETS:
        raise ValueError(
            f"ACTIVE_AI_PERSONALITY must name an existing preset: {ACTIVE_AI_PERSONALITY}"
        )


_validate_behavior_settings()


def build_ai_system_instruction(personality_name: str | None = None) -> str:
    """Return the selected AI personality with the current UTC date."""

    from datetime import datetime, timezone

    selected_personality = personality_name or ACTIVE_AI_PERSONALITY
    try:
        personality = AI_PERSONALITY_PRESETS[selected_personality]
    except KeyError as error:
        raise ValueError(f"Unknown AI personality: {selected_personality}") from error
    current_datetime = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC (%A)")
    return personality.format(
        current_datetime=current_datetime,
        ai_max_response_length=AI_MAX_RESPONSE_LENGTH,
    )
