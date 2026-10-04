"""Informational commands."""

from app.commands.registry import CommandRegistry
from app.config.commands import (
    COMMANDS_COOLDOWN_SECONDS,
    HELP_COOLDOWN_SECONDS,
    UPTIME_COOLDOWN_SECONDS,
    WEATHER_COOLDOWN_SECONDS,
)
from app.utils.cooldown import CooldownPolicy
from app.utils.text import format_duration
from app.twitch.permissions import Permission
from app.services.weather import WeatherServiceError, format_weather_response, weather_language_for_query


def register_weather_commands(registry: CommandRegistry) -> None:
    @registry.command(
        "weather",
        help_text="!weather <city>",
        cooldown=CooldownPolicy(global_seconds=WEATHER_COOLDOWN_SECONDS),
        argument_validator=lambda arguments: bool(arguments),
    )
    async def weather(context, arguments: str) -> None:
        if not arguments:
            await context.reply("Usage: !weather <city>")
            return
        username = context.message.author.username.lstrip("@")
        try:
            report = await context.services.weather.get_current_weather(arguments)
        except WeatherServiceError:
            language = weather_language_for_query(arguments)
            unavailable = {
                "en": "weather is currently unavailable",
                "ru": "погода сейчас недоступна",
                "uk": "погода зараз недоступна",
            }[language]
            await context.reply(f"@{username}, {unavailable}.")
            return
        if report is None:
            language = weather_language_for_query(arguments)
            not_found = {
                "en": "could not find that city",
                "ru": "не смог найти такой город",
                "uk": "не вдалося знайти це місто",
            }[language]
            await context.reply(f"@{username}, {not_found}.")
            return
        await context.reply(f"@{username}, {format_weather_response(report, arguments)}")


def register_info_commands(registry: CommandRegistry) -> None:
    @registry.command(
            "help",
            help_text="!help",
            cooldown=CooldownPolicy(global_seconds=HELP_COOLDOWN_SECONDS),
        )
    async def help_command(context, arguments: str) -> None:
        await context.reply(" ".join(registry.help_entries()))

    @registry.command(
        "commands",
        help_text="!commands",
        required_permission=Permission.MODERATOR,
        cooldown=CooldownPolicy(global_seconds=COMMANDS_COOLDOWN_SECONDS),
    )
    async def commands_command(context, arguments: str) -> None:
        await context.reply(" ".join(registry.help_entries()))

    @registry.command(
        "uptime",
        help_text="!uptime",
        required_permission=Permission.MODERATOR,
        cooldown=CooldownPolicy(global_seconds=UPTIME_COOLDOWN_SECONDS),
        argument_validator=lambda arguments: not arguments,
    )
    async def uptime(context, arguments: str) -> None:
        if arguments.strip():
            await context.reply("Usage: !uptime")
            return

        await context.reply(
            f"Uptime: {format_duration(context.services.runtime_state.elapsed_seconds())}"
        )
