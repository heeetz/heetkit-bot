"""Lightweight fun commands."""

from random import choice

from app.config.commands import (
    FATE_COOLDOWN_SECONDS,
    PING_COOLDOWN_SECONDS,
    TG_BURST_DELAY,
)
from app.commands.registry import CommandRegistry
from app.utils.cooldown import CooldownPolicy
from app.twitch.permissions import Permission
from app.runtime_paths import RuntimePaths
from app.fun_settings import FATES, FunSettingsStore



def _valid_tg_arguments(arguments: str) -> bool:
    try:
        count = int(arguments.strip())
    except ValueError:
        return False
    return 1 <= count <= 10


def random_fate(fates: tuple[str, ...] = FATES) -> str:
    return choice(fates)


def load_fun_settings() -> tuple[str, tuple[str, ...]]:
    """Local responses for built-in commands; absent files use neutral starters."""
    store = FunSettingsStore(RuntimePaths.default().config / "fun_settings.json")
    return store.tg_message, store.fates


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
        "fate",
        help_text="!fate",
        cooldown=CooldownPolicy(global_seconds=FATE_COOLDOWN_SECONDS),
        argument_validator=lambda arguments: not arguments,
    )
    async def fate(context, arguments: str) -> None:
        if arguments:
            await context.reply("Usage: !fate")
            return
        username = context.message.author.username.lstrip("@")
        await context.reply(f"@{username}, {random_fate(fun_settings.fates)}")
