"""Commands backed by the replaceable AI service."""

from app.commands.registry import CommandRegistry
from app.services.ai_request_policy import PolicyDecision
from app.twitch.permissions import Permission
from app.utils.cooldown import CooldownPolicy
from app.config.commands import ASK_COOLDOWN_SECONDS
from app.utils.logging import operator_event


def register_ai_commands(registry: CommandRegistry) -> None:
    def ask_pre_check(context, arguments: str) -> bool:
        clean_args = arguments.strip()
        if not clean_args:
            context.skip("invalid_arguments")
            operator_event(context.logger, "command.outcome", "invalid_arguments")
            return False
        from app.config.ai_setup import effective_ai_setup
        if len(clean_args) > effective_ai_setup(getattr(context.services, "settings", None)).max_question_length:
            context.skip("invalid_arguments")
            operator_event(context.logger, "command.outcome", "invalid_arguments", reason="question_too_long")
            return False
        policy_decision = context.services.ai_request_policy.check(clean_args)
        if policy_decision == PolicyDecision.IGNORE:
            context.skip("filters")
            operator_event(context.logger, "command.outcome", "filters", reason="protected_policy")
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
                entries = await memory_service.get_recent(context.message.author.twitch_user_id, channel_id=context.message.channel_id)
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
        status = getattr(reply, "status", "success" if reply.is_available else "api_error")
        if not reply.is_available or not reply.text:
            if status in {"output_blocked", "provider_unavailable", "question_too_long"}:
                context.skip("filters" if status == "output_blocked" else "ai_unavailable" if status == "provider_unavailable" else "invalid_arguments")
            else:
                context.fail("provider_failure")
        operator_event(context.logger, "ai.result",
                       "generated" if reply.is_available and reply.text else
                       "filters" if status == "output_blocked" else
                       "ai_unavailable" if status == "provider_unavailable" else "provider_failure",
                       reason=status)
        if reply.is_available and reply.text:
            username = context.message.author.username.lstrip("@")
            # Twitch's envelope includes the mention; do not split or chop citations.
            outgoing = f"@{username} {reply.text}"
            try:
                outgoing.encode("utf-8")
                valid_encoding = True
            except UnicodeError:
                valid_encoding = False
            if len(outgoing) > 500 or not valid_encoding:
                context.fail("outgoing_envelope")
                operator_event(context.logger, "ai.result", "provider_failure", reason="outgoing_envelope")
                return
            delivered = await context.reply(outgoing)
            memory_still_enabled = memory_enabled and (
                runtime_state is None or runtime_state.ai_memory_enabled
            )
            if delivered and memory_still_enabled:
                try:
                    await memory_service.save_exchange(
                        twitch_user_id=context.message.author.twitch_user_id,
                        request_text=clean_args,
                        response_text=reply.text,
                        channel_id=context.message.channel_id,
                    )
                except Exception:
                    context.logger.exception("Could not save AI memory")

    @registry.command(
        "erase",
        required_permission=Permission.BROADCASTER,
        minimum_permission=Permission.MODERATOR,
        hidden=True,
    )
    async def erase_memory(context, arguments: str) -> None:
        parts = arguments.strip().split(maxsplit=1)
        if not parts:
            context.skip("invalid_arguments")
            return
        target_username = parts[0].lstrip("@")
        if not target_username:
            context.skip("invalid_arguments")
            return

        user = await context.services.users.get_by_username(target_username, channel_id=context.message.channel_id)
        if user is not None:
            await context.services.memory.erase_for_user(user.twitch_user_id, channel_id=context.message.channel_id)
            context.complete()
        else:
            context.skip("no_retained_user")
