"""Private owner command for erasing a user's AI memory."""

from app.commands.registry import CommandRegistry
from app.twitch.permissions import Permission


def register_memory_commands(registry: CommandRegistry) -> None:
    @registry.command(
        "erase",
        required_permission=Permission.BROADCASTER,
        hidden=True,
    )
    async def erase_memory(context, arguments: str) -> None:
        target_username = arguments.strip().split(maxsplit=1)[0].lstrip("@")
        if not target_username:
            return

        user = await context.services.users.get_user_by_username(target_username)
        if user is not None:
            await context.services.memory.erase_for_user(user.twitch_user_id)
