"""Lightweight fun commands."""

from random import choice
import json
import logging

from config import (
    FORECAST_COOLDOWN_SECONDS,
    PING_COOLDOWN_SECONDS,
    TG_BURST_DELAY,
    TG_MESSAGE,
)
from app.commands.registry import CommandRegistry
from app.utils.cooldown import CooldownPolicy
from app.twitch.permissions import Permission
from app.runtime_paths import RuntimePaths



def _valid_tg_arguments(arguments: str) -> bool:
    try:
        count = int(arguments.strip())
    except ValueError:
        return False
    return 1 <= count <= 10


FORECASTS = (
    'Tomorrow brings a new opportunity.',
)


def random_forecast(forecasts: tuple[str, ...] = FORECASTS) -> str:
    return choice(forecasts)


def load_fun_settings() -> tuple[str, tuple[str, ...]]:
    """Local responses for built-in commands; absent files use neutral starters."""
    path = RuntimePaths.default().config / "fun_settings.json"
    if not path.exists():
        return TG_MESSAGE, FORECASTS
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("version") != 1:
            raise ValueError("Unsupported fun settings")
        message = payload.get("tg_message", TG_MESSAGE)
        forecasts = payload.get("forecasts", list(FORECASTS))
        if not isinstance(forecasts, list) or not 1 <= len(forecasts) <= 1000:
            raise ValueError("Invalid forecasts")
        if any(not isinstance(value, str) or not value.strip() or len(value.encode("utf-8")) > 450
               for value in [message, *forecasts]):
            raise ValueError("Invalid command response")
        return message, tuple(forecasts)
    except (OSError, UnicodeError, ValueError):
        logging.getLogger(__name__).warning("Could not load local fun settings; using neutral defaults")
        return TG_MESSAGE, FORECASTS


def register_fun_commands(registry: CommandRegistry) -> None:
    tg_message, forecasts = load_fun_settings()
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

        await context.reply_burst(tg_message, count, delay=TG_BURST_DELAY)

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
        await context.reply(f"@{username}, {random_forecast(forecasts)}")
