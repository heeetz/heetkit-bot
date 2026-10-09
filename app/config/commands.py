"""Application-owned command starters and operational timing.

Effective cooldowns and fun responses are overlaid by their profile stores.
Burst timing remains an internal limit, not an editable command preference.
"""

TG_BURST_DELAY = 0.01
TG_MESSAGE = "Configure your community link in config/fun_settings.json."
PING_COOLDOWN_SECONDS = 10.0
HELP_COOLDOWN_SECONDS = 10.0
COMMANDS_COOLDOWN_SECONDS = 15.0
UPTIME_COOLDOWN_SECONDS = 15.0
FATE_COOLDOWN_SECONDS = 15.0
WEATHER_COOLDOWN_SECONDS = 15.0
FOLLOWAGE_COOLDOWN_SECONDS = 10.0
SEEN_COOLDOWN_SECONDS = 15.0
ASK_COOLDOWN_SECONDS = 25.0
