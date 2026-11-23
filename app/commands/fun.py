"""Lightweight fun commands."""

from random import choice

from app.config.commands import (
    FATE_COOLDOWN_SECONDS,
    PING_COOLDOWN_SECONDS,
)
from app.commands.registry import CommandRegistry
from app.utils.cooldown import CooldownPolicy
from app.twitch.permissions import Permission
from app.runtime_paths import RuntimePaths
from app.config_file import ConfigFile
from app.fun_settings import FATES, FunSettingsStore



def random_fate(fates: tuple[str, ...] = FATES) -> str:
    return choice(fates)


def register_fun_commands(registry: CommandRegistry, fun_settings: FunSettingsStore | None = None) -> None:
    fun_settings = fun_settings or FunSettingsStore(ConfigFile(RuntimePaths.default().config_file))
    @registry.command(
        "ping",
        description="Check that HeetKit responds.",
        help_text="!ping",
        cooldown=CooldownPolicy(global_seconds=PING_COOLDOWN_SECONDS),
        required_permission=Permission.MODERATOR,
    )
    async def ping(context, arguments: str) -> None:
        await context.reply("pong")

    @registry.command(
        "fate",
        description="Send a random prediction.",
        default_send_as="mention",
        help_text="!fate",
        cooldown=CooldownPolicy(global_seconds=FATE_COOLDOWN_SECONDS),
        argument_validator=lambda arguments: not arguments,
    )
    async def fate(context, arguments: str) -> None:
        if arguments:
            await context.reply(f"Usage: {context.invocation('fate')}")
            return
        await context.reply(random_fate(fun_settings.fates), legacy_mention=True, separator=", ")
