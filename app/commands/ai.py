"""Commands backed by the replaceable AI service."""

from app.commands.registry import CommandRegistry
from app.services.ai_request_policy import PolicyDecision
from app.twitch.permissions import Permission
from app.utils.cooldown import CooldownPolicy
from app.config.commands import ASK_COOLDOWN_SECONDS


def register_ai_commands(registry: CommandRegistry) -> None:
    def ask_pre_check(context, arguments: str) -> bool:
        clean_args = arguments.strip()
        if not clean_args:
            return False
        policy_decision = context.services.ai_request_policy.check(clean_args)
        if policy_decision == PolicyDecision.IGNORE:
            return False
        return True

    @registry.command(
        "ask",
        help_text="!ask <question>",
        cooldown=CooldownPolicy(per_user_seconds=0.0, global_seconds=ASK_COOLDOWN_SECONDS),
        pre_check=ask_pre_check,
        requires_ai=True,
    )
    async def ask(context, arguments: str) -> None:
        clean_args = arguments.strip()
        if not clean_args:
            return

        memory_service = getattr(context.services, "memory", None)
        runtime_state = getattr(context.services, "runtime_state", None)
        memory_enabled = memory_service is not None and (
            runtime_state is None or runtime_state.ai_memory_enabled
        )
        memory_context = None
        if memory_enabled:
            try:
                entries = await memory_service.get_recent(context.message.author.twitch_user_id)
                memory_context = memory_service.format_context(entries)
            except Exception:
                context.logger.exception("Could not load AI memory")

        stream_category = None
        twitch_service = getattr(context.services, "twitch", None)
        if twitch_service is not None:
            try:
                stream_category = await twitch_service.get_current_category()
            except Exception:
                context.logger.exception("Could not load Twitch stream category")

        reply = await context.services.ai.generate_reply(
            prompt=clean_args,
            user_id=context.message.author.twitch_user_id,
            memory_context=memory_context,
            stream_category=stream_category,
        )
        if reply.is_available and reply.text:
            username = context.message.author.username.lstrip("@")
            delivered = await context.reply(f"@{username} {reply.text}")
            memory_still_enabled = memory_enabled and (
                runtime_state is None or runtime_state.ai_memory_enabled
            )
            if delivered and memory_still_enabled:
                try:
                    await memory_service.save_exchange(
                        twitch_user_id=context.message.author.twitch_user_id,
                        request_text=clean_args,
                        response_text=reply.text,
                    )
                except Exception:
                    context.logger.exception("Could not save AI memory")

    @registry.command(
        "erase",
        required_permission=Permission.BROADCASTER,
        hidden=True,
    )
    async def erase_memory(context, arguments: str) -> None:
        parts = arguments.strip().split(maxsplit=1)
        if not parts:
            return
        target_username = parts[0].lstrip("@")
        if not target_username:
            return

        user = await context.services.users.get_by_username(target_username)
        if user is not None:
            await context.services.memory.erase_for_user(user.twitch_user_id)
