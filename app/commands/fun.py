"""Lightweight fun commands."""

from random import choice

from app.config import (
    FORECAST_COOLDOWN_SECONDS,
    PING_COOLDOWN_SECONDS,
    TG_BURST_DELAY,
    TG_MESSAGE,
    WEATHER_COOLDOWN_SECONDS,
)
from app.commands.registry import CommandRegistry
from app.services.weather import WeatherServiceError, format_weather_response, weather_language_for_query
from app.utils.cooldown import CooldownPolicy
from app.twitch.permissions import Permission



def _valid_tg_arguments(arguments: str) -> bool:
    try:
        count = int(arguments.strip())
    except ValueError:
        return False
    return 1 <= count <= 10


FORECASTS = (
    "завтра ты найдёшь свою альтушечку. Рост 170, третий размер, характер — не очень.",
    "завтра твой IQ поднимется на 20 пунктов. Жаль, всего на пять минут.",
    "завтра тебе кто-то кринет ГАНДОООООООООООНЫ",
    "завтра можешь не идти в школу",
    "завтра буде циркумфлекс коса рыска коса рыска",
    "завтра хз че будет еще не придумал отдыхай пацан",
    "завтра тебя отстрапонит альтушечка",
    "завтра сева выйдет в +120 эло",
    "завтра сева не выйдет в +эло",
    "завтра севе будут мешать комары",
    "возможно завтра все модеры перестануть быть даунами",
    "возможно можно",
    "ВАСЬ",
    "завтра будет завозик WW",
    "монеси уже голенький",
    "пацан",
)


def random_forecast() -> str:
    return choice(FORECASTS)


def register_fun_commands(registry: CommandRegistry) -> None:
    @registry.command(
        "ping",
        help_text="!ping",
        cooldown=CooldownPolicy(global_seconds=PING_COOLDOWN_SECONDS),
        required_permission=Permission.MODERATOR,
    )
    async def ping(context, arguments: str) -> None:
        await context.reply("pong")

    @registry.command(
        "tg",
        help_text="!tg <1-10>",
        required_permission=Permission.MODERATOR,
        argument_validator=_valid_tg_arguments,
    )
    async def tg(context, arguments: str) -> None:
        try:
            count = int(arguments.strip())
        except ValueError:
            await context.reply("Использование: !tg <1-10>")
            return

        if not 1 <= count <= 10:
            await context.reply("Количество должно быть от 1 до 10.")
            return

        await context.reply_burst(TG_MESSAGE, count, delay=TG_BURST_DELAY)

    @registry.command(
        "forecast",
        help_text="!forecast",
        cooldown=CooldownPolicy(global_seconds=FORECAST_COOLDOWN_SECONDS),
        argument_validator=lambda arguments: not arguments,
    )
    async def forecast(context, arguments: str) -> None:
        if arguments:
            await context.reply("Usage: !forecast")
            return
        username = context.message.author.username.lstrip("@")
        await context.reply(f"@{username}, {random_forecast()}")

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
