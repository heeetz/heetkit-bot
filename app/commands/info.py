"""Informational commands."""

from app.commands.registry import CommandRegistry
from app.config import COMMANDS_COOLDOWN_SECONDS, HELP_COOLDOWN_SECONDS, UPTIME_COOLDOWN_SECONDS
from app.utils.cooldown import CooldownPolicy
from app.utils.text import format_duration
from app.twitch.permissions import Permission


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
            f"Uptime: {format_duration(context.services.runtime.elapsed_seconds())}"
        )
