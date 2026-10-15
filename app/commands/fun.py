"""Lightweight fun commands."""

from random import choice

from app.config.commands import (
    FATE_COOLDOWN_SECONDS,
    PING_COOLDOWN_SECONDS,
    BURST_HARD_MAX_COUNT,
)
from app.commands.registry import CommandRegistry
from app.utils.cooldown import CooldownPolicy
from app.twitch.permissions import Permission
from app.runtime_paths import RuntimePaths
from app.fun_settings import FATES, FunSettingsStore



def _tg_count(arguments: str) -> int | None:
    value = arguments.strip()
    if not value:
        return 1
    if not value.isascii() or not value.isdecimal():
        return None
    count = int(value)
    return count if 1 <= count <= BURST_HARD_MAX_COUNT else None


def _valid_tg_arguments(arguments: str) -> bool:
    return _tg_count(arguments) is not None


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
        help_text="!tg [1-20]",
        required_permission=Permission.MODERATOR,
        minimum_permission=Permission.MODERATOR,
        argument_validator=_valid_tg_arguments,
        pre_check=lambda context, arguments: _tg_count(arguments) <= context.burst_max_count,
    )
    async def tg(context, arguments: str) -> None:
        count = _tg_count(arguments)
        if count is None or count > context.burst_max_count:
            await context.reply(f"Usage: !tg [1-{context.burst_max_count}] (default: 1)")
            return

        await context.reply_burst(fun_settings.tg_message, count)

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
