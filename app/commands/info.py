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


HELP_MESSAGE_BYTES = 450


def command_help_page(entries: tuple[str, ...], invocation: str, arguments: str) -> str:
    """Return one bounded page so ordinary output limiting still applies."""
    page_text = arguments.strip() or "1"
    if not page_text.isascii() or not page_text.isdecimal() or len(page_text) > 9:
        return f"Usage: {invocation} [page]"
    page = int(page_text)
    if not entries:
        return "No public commands are enabled."
    # Every page contains at least one entry; this reserves enough space for
    # the largest possible page numbers before packing UTF-8 command names.
    digits = "9" * len(str(len(entries)))
    overhead = len(f"Commands ({digits}/{digits}):  | Next: {invocation} {digits}".encode("utf-8"))
    pages: list[str] = []
    current = ""
    for entry in entries:
        candidate = f"{current} {entry}" if current else entry
        if current and len(candidate.encode("utf-8")) + overhead > HELP_MESSAGE_BYTES:
            pages.append(current)
            current = entry
        else:
            current = candidate
    pages.append(current)
    if not 1 <= page <= len(pages):
        return f"Choose a page from 1 to {len(pages)}: {invocation} [page]"
    response = f"Commands ({page}/{len(pages)}): {pages[page - 1]}"
    if page < len(pages):
        response += f" | Next: {invocation} {page + 1}"
    return response


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
    async def reply_with_help(context, arguments: str, command: str) -> None:
        prefix = getattr(getattr(context.services, "settings", None), "command_prefix", "!")
        entries = registry.help_entries(
            getattr(context.services, "runtime_state", None),
            getattr(context.services, "custom_commands", None),
            prefix,
        )
        await context.reply(command_help_page(entries, f"{prefix}{command}", arguments))

    @registry.command(
            "help",
            help_text="!help [page]",
            cooldown=CooldownPolicy(global_seconds=HELP_COOLDOWN_SECONDS),
        )
    async def help_command(context, arguments: str) -> None:
        await reply_with_help(context, arguments, "help")

    @registry.command(
        "commands",
        help_text="!commands [page]",
        required_permission=Permission.MODERATOR,
        cooldown=CooldownPolicy(global_seconds=COMMANDS_COOLDOWN_SECONDS),
    )
    async def commands_command(context, arguments: str) -> None:
        await reply_with_help(context, arguments, "commands")

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
