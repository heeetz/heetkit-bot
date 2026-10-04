"""Lightweight fun commands."""

from random import choice

from config import (
    FORECAST_COOLDOWN_SECONDS,
    PING_COOLDOWN_SECONDS,
    TG_BURST_DELAY,
)
from app.commands.registry import CommandRegistry
from app.utils.cooldown import CooldownPolicy
from app.twitch.permissions import Permission
from app.runtime_paths import RuntimePaths
from app.fun_settings import FORECASTS, FunSettingsStore



def _valid_tg_arguments(arguments: str) -> bool:
    try:
        count = int(arguments.strip())
    except ValueError:
        return False
    return 1 <= count <= 10


def random_forecast(forecasts: tuple[str, ...] = FORECASTS) -> str:
    return choice(forecasts)


def load_fun_settings() -> tuple[str, tuple[str, ...]]:
    """Local responses for built-in commands; absent files use neutral starters."""
    store = FunSettingsStore(RuntimePaths.default().config / "fun_settings.json")
    return store.tg_message, store.forecasts


def register_fun_commands(registry: CommandRegistry, fun_settings: FunSettingsStore | None = None) -> None:
    fun_settings = fun_settings or FunSettingsStore(RuntimePaths.default().config / "fun_settings.json")
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

        await context.reply_burst(fun_settings.tg_message, count, delay=TG_BURST_DELAY)

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
        await context.reply(f"@{username}, {random_forecast(fun_settings.forecasts)}")
