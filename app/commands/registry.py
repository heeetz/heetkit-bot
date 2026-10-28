"""Declarative command registration and fault-isolated dispatching."""

import logging
import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from contextlib import nullcontext

from app.command_settings import CommandSettings
from app.config.commands import TG_DEFAULT_MAX_COUNT
from app.custom_commands import CustomCommand, CustomCommandStore, render_response
from app.message_triggers import MessageTriggerStore
from app.runtime_state import RuntimeState
from app.services.facade import ApplicationServices
from app.twitch.events import IncomingChatMessage
from app.twitch.permissions import Permission, has_permission
from app.utils.cooldown import CooldownManager, CooldownPolicy
from app.utils.output_limiter import OutputLimiter
from app.utils.text import normalize_command_name, parse_command
from app.utils.logging import event_metadata, operator_event, operator_event_scope
from app.twitch.sending import ChatSender, ChatSessionClosedError


CommandHandler = Callable[["CommandContext", str], Awaitable[None]]
ArgumentValidator = Callable[[str], bool]


@dataclass(frozen=True, slots=True)
class CommandDefinition:
    name: str
    handler: CommandHandler
    aliases: tuple[str, ...] = ()
    help_text: str | None = None
    required_permission: Permission = Permission.USER
    cooldown: CooldownPolicy = field(default_factory=CooldownPolicy)
    pre_check: Callable[[CommandContext, str], bool] | None = None
    argument_validator: ArgumentValidator | None = None
    silent_invalid_arguments: bool = False
    hidden: bool = False
    enabled_by_default: bool = True
    requires_ai: bool = False
    minimum_permission: Permission = Permission.USER

    @property
    def identity_editable(self) -> bool:
        # Ask's canonical name participates in pre-log AI policy; keep it fixed.
        return not self.hidden and not self.requires_ai

    @property
    def default_settings(self) -> CommandSettings:
        return CommandSettings(
            enabled=self.enabled_by_default,
            cooldown=self.cooldown,
            permission=self.required_permission,
            aliases=self.aliases,
        )


@dataclass(frozen=True, slots=True)
class CommandContext:
    message: IncomingChatMessage
    services: ApplicationServices
    logger: logging.Logger
    output_limiter: OutputLimiter | None = None
    burst_interval_ms: int = 0
    burst_max_count: int = TG_DEFAULT_MAX_COUNT

    async def reply(self, content: str) -> bool:
        return await self._sender().reply(content)

    def _sender(self) -> ChatSender:
        return ChatSender(self.message.respond, self.logger, self.output_limiter, self.message.send_session)

    async def reply_burst(
        self,
        content: str,
        count: int,
        interval_ms: int | None = None,
    ) -> list[object]:
        """Await a bounded batch of transport sends; retain every result or exception.

        TwitchIO/Twitch still own API rejection and rate limiting. Cancelling the
        batch cancels its children and waits for their cleanup through gather.
        """
        return await self._sender().reply_burst(
            content, count, self.burst_interval_ms if interval_ms is None else interval_ms, self.burst_max_count,
        )


class CommandRegistry:
    def __init__(self) -> None:
        self._commands: dict[str, CommandDefinition] = {}

    def command(
        self,
        name: str,
        *,
        aliases: tuple[str, ...] = (),
        help_text: str | None = None,
        enabled_by_default: bool = True,
        required_permission: Permission = Permission.USER,
        cooldown: CooldownPolicy | None = None,
        pre_check: Callable[[CommandContext, str], bool] | None = None,
        argument_validator: ArgumentValidator | None = None,
        silent_invalid_arguments: bool = False,
        hidden: bool = False,
        requires_ai: bool = False,
        minimum_permission: Permission = Permission.USER,
    ) -> Callable[[CommandHandler], CommandHandler]:
        def decorator(handler: CommandHandler) -> CommandHandler:
            self.register(
                CommandDefinition(
                    name=name,
                    handler=handler,
                    aliases=aliases,
                    help_text=help_text,
                    enabled_by_default=enabled_by_default,
                    required_permission=required_permission,
                    cooldown=cooldown or CooldownPolicy(),
                    pre_check=pre_check,
                    argument_validator=argument_validator,
                    silent_invalid_arguments=silent_invalid_arguments,
                    hidden=hidden,
                    requires_ai=requires_ai,
                    minimum_permission=minimum_permission,
                )
            )
            return handler

        return decorator

    def register(self, definition: CommandDefinition) -> None:
        command_names = (definition.name, *definition.aliases)
        normalized_names = tuple(normalize_command_name(name) for name in command_names)
        if not all(normalized_names):
            raise ValueError("Command names cannot be empty.")
        if len(set(normalized_names)) != len(normalized_names):
            raise ValueError("A command cannot repeat its own name or alias.")
        duplicates = [name for name in normalized_names if name in self._commands]
        if duplicates:
            raise ValueError(f"Command name already registered: {duplicates[0]}")

        normalized_definition = CommandDefinition(
            name=normalized_names[0],
            handler=definition.handler,
            aliases=normalized_names[1:],
            help_text=definition.help_text,
            enabled_by_default=definition.enabled_by_default,
            required_permission=definition.required_permission,
            cooldown=definition.cooldown,
            pre_check=definition.pre_check,
            argument_validator=definition.argument_validator,
            silent_invalid_arguments=definition.silent_invalid_arguments,
            hidden=definition.hidden,
            requires_ai=definition.requires_ai,
            minimum_permission=definition.minimum_permission,
        )
        for command_name in normalized_names:
            self._commands[command_name] = normalized_definition

    def get(self, name: str) -> CommandDefinition | None:
        return self._commands.get(normalize_command_name(name))

    def definitions(self) -> tuple[CommandDefinition, ...]:
        definitions = {definition.name: definition for definition in self._commands.values()}
        return tuple(definitions[name] for name in sorted(definitions))

    def names(self) -> tuple[str, ...]:
        return tuple(
            sorted({definition.name for definition in self._commands.values() if not definition.hidden})
        )

    def help_entries(
        self,
        runtime_state: RuntimeState | None = None,
        custom_commands: CustomCommandStore | None = None,
        prefix: str = "!",
    ) -> tuple[str, ...]:
        # Capture the same namespace used by dispatch, including runtime-only
        # Apply changes. No cached public list can outlive an edit or restore.
        entries: dict[str, str] = {}
        with runtime_state.command_namespace_lock if runtime_state is not None else nullcontext():
            stream_status = None if runtime_state is None else runtime_state.command_stream_status()
            def visible(availability: str) -> bool:
                return stream_status not in ("live", "offline") or availability in (
                    "anytime", "live_only" if stream_status == "live" else "offline_only")
            for definition in self.definitions():
                settings = definition.default_settings if runtime_state is None else runtime_state.get_command_settings(definition.name)
                if definition.hidden or not settings.enabled or settings.removed:
                    continue
                if not visible(settings.stream_availability):
                    continue
                usage = "" if definition.help_text is None else definition.help_text.partition(" ")[2]
                if definition.name == "tg":
                    usage = f"[1-{settings.burst_max_count}]"
                for name in (definition.name, *settings.aliases):
                    entries[name] = f"{prefix}{name}" + (f" {usage}" if usage else "")
            if custom_commands is not None:
                for command in custom_commands.list():
                    if not command.enabled:
                        continue
                    if not visible(command.stream_availability):
                        continue
                    usage = " [1-10]" if command.response_mode == "burst" and command.burst_allow_override else ""
                    for name in (command.name, *command.aliases):
                        entries[name] = f"{prefix}{name}{usage}"
        return tuple(entries[name] for name in sorted(entries))


def command_unavailable_reason(definition: CommandDefinition, services: ApplicationServices) -> str | None:
    if not definition.requires_ai:
        return None
    provider = getattr(services, "ai", None)
    if provider is None or not getattr(provider, "is_available", False):
        return "AI features are optional. Configure a usable Gemini API key/provider to use this command."
    return None


class CommandDispatcher:
    def __init__(
        self,
        registry: CommandRegistry,
        cooldowns: CooldownManager,
        logger: logging.Logger,
        command_prefix: str,
        max_arguments_length: int = 300,
        output_limiter: OutputLimiter | None = None,
        ai_cooldown_bypass_user_id: str | None = None,
        runtime_state: RuntimeState | None = None,
        custom_commands: CustomCommandStore | None = None,
        message_triggers: MessageTriggerStore | None = None,
    ) -> None:
        self._registry = registry
        self._cooldowns = cooldowns
        self._logger = logger
        self._command_prefix = command_prefix
        self._max_arguments_length = max_arguments_length
        self._output_limiter = output_limiter
        self._ai_cooldown_bypass_user_id = ai_cooldown_bypass_user_id
        self._runtime_state = runtime_state
        self._custom_commands = custom_commands
        self._message_triggers = message_triggers

    def event_scope(self, message: IncomingChatMessage):
        parsed = parse_command(message.content, self._command_prefix)
        name = parsed[0] if parsed else None
        definition = self._builtin_definition(name) if name else None
        custom = (self._custom_commands.get_by_name(name)
                  if name and definition is None and self._custom_commands else None)
        return operator_event_scope(
            channel=message.channel, username=message.author.username,
            input_message_id=message.message_id,
            source="command" if parsed else "announcement",
            command=definition.name if definition else custom.name if custom else name,
            command_id=f"custom:{custom.id}" if custom else definition.name if definition else None,
            invoked_name=name,
        )

    def _outcome(self, outcome: str, **context) -> None:
        operator_event(self._logger, "command.outcome", outcome, **context)

    def is_ai_command(self, message: IncomingChatMessage) -> bool:
        parsed = parse_command(message.content, self._command_prefix)
        definition = self._builtin_definition(parsed[0]) if parsed else None
        return definition is not None and definition.requires_ai

    def _builtin_definition(self, command_name: str) -> CommandDefinition | None:
        definition = self._registry.get(command_name)
        if definition is not None and self._runtime_state is not None and command_name != definition.name:
            if command_name not in self._runtime_state.get_command_settings(definition.name).aliases:
                definition = None
        if definition is None and self._runtime_state is not None:
            canonical = self._runtime_state.resolve_command_alias(command_name)
            if canonical is not None:
                definition = self._registry.get(canonical)
        return definition

    def is_ai_request_blocked(self, message: IncomingChatMessage, services: ApplicationServices) -> bool:
        """Also used before content logging in the Twitch adapter."""
        blocks = getattr(services, "ai_user_blocks", None)
        if blocks is None:
            return False
        parsed = parse_command(message.content, self._command_prefix)
        definition = self._builtin_definition(parsed[0]) if parsed is not None else None
        if definition is None or definition.name != "ask" or not blocks.is_blocked(
            message.author.twitch_user_id, message.author.username,
        ):
            return False
        try:
            blocks.remember_observed_id(message.author.username, message.author.twitch_user_id)
        except (ValueError, OSError):
            self._logger.warning("Could not persist observed AI block account ID; request remains blocked")
        operator_event(self._logger, "ai_user_blocked", "ai_user_blocked", reason="ai_user_blocked")
        return True

    async def _dispatch_trigger(self, message: IncomingChatMessage, services: ApplicationServices) -> bool:
        if self._message_triggers is None or message.is_outgoing:
            return False
        for trigger in self._message_triggers.list():
            if not trigger.enabled or not trigger.matches(message.content):
                continue
            if random.random() >= trigger.probability:
                continue
            with operator_event_scope(command_id=f"trigger:{trigger.id}", source="announcement"):
                operator_event(self._logger, "command.input", "received")
                cooldown = self._cooldowns.check_and_record(
                    command_name=f"trigger:{trigger.id}",
                    user_id=message.author.twitch_user_id,
                    policy=CooldownPolicy(global_seconds=trigger.cooldown_seconds),
                )
                if not cooldown.allowed:
                    self._outcome("cooldown", retry_after_seconds=round(cooldown.retry_after, 2))
                    continue
                response = random.choice(trigger.responses)
                operator_event(self._logger, "command.invoke", "executing")
                await CommandContext(message, services, self._logger, self._output_limiter).reply(response)
                operator_event(self._logger, "command.complete", "handler_completed")
                return True
        return False

    async def _run_custom_command(self, command: CustomCommand, context: CommandContext, arguments: str) -> None:
        count = command.burst_count
        if command.response_mode == "burst" and command.burst_allow_override and arguments.strip():
            count_argument, *tail = arguments.split(maxsplit=1)
            try:
                count = int(count_argument)
            except ValueError:
                self._outcome("invalid_arguments")
                return
            if not 1 <= count <= 10:
                self._outcome("invalid_arguments")
                return
            # The count is a control argument; templates see the remaining text.
            arguments = tail[0] if tail else ""
        template = random.choice(command.responses)
        sender = context.message.author.username.lstrip("@")
        random_user = sender
        if "{random_user}" in template:
            try:
                excluded = (context.message.author.twitch_user_id, context.services.settings.twitch_bot_user_id)
                recent = await context.services.users.recent_usernames(exclude_user_ids=excluded)
                eligible = [name for name in recent if name.casefold() != context.services.settings.twitch_bot_username.casefold()]
                if eligible:
                    random_user = random.choice(eligible)
            except Exception:
                self._logger.exception("Could not load recent chatters for custom command")
        response = render_response(command, arguments, sender, random_user, template=template)
        if response:
            if command.response_mode == "burst":
                await context.reply_burst(response, count, interval_ms=command.burst_interval_ms)
            else:
                await context.reply(response)

    async def dispatch(self, message: IncomingChatMessage, services: ApplicationServices) -> bool:
        if message.is_outgoing:
            return False
        with self.event_scope(message):
            try:
                return await self._dispatch(message, services)
            except asyncio.CancelledError:
                self._outcome("cancelled")
                raise

    async def _dispatch(self, message: IncomingChatMessage, services: ApplicationServices) -> bool:
        try:
            # Keep the transport-neutral boundary safe as well as Twitch ingress.
            if message.is_outgoing:
                return False
            if self.is_ai_request_blocked(message, services):
                return True
            parsed_command = parse_command(message.content, self._command_prefix)
            if parsed_command is None:
                if message.content.strip().startswith(self._command_prefix):
                    return False
                return await self._dispatch_trigger(message, services)

            command_name, arguments = parsed_command
            operator_event(self._logger, "command.input", "received", text=message.content)
            definition = self._builtin_definition(command_name)
            custom = None
            if definition is None:
                custom = None if self._custom_commands is None else self._custom_commands.get_by_name(command_name)
                if custom is None:
                    self._outcome("unknown_command")
                    return False
                async def custom_handler(context: CommandContext, tail: str) -> None:
                    await self._run_custom_command(custom, context, tail)
                definition = CommandDefinition(name=custom.name, handler=custom_handler)
                permission = max(custom.permission, Permission.MODERATOR) if custom.response_mode == "burst" else custom.permission
                settings = CommandSettings(enabled=custom.enabled, permission=permission, cooldown=custom.cooldown,
                                           stream_availability=custom.stream_availability)
            else:
                settings = (
                    definition.default_settings
                    if self._runtime_state is None
                    else self._runtime_state.get_command_settings(definition.name)
                )
            cooldown_key = f"custom:{custom.id}" if custom is not None else definition.name

            command_output_limiter = (
                None if definition.name == "tg" or (custom is not None and custom.response_mode == "burst") else self._output_limiter
            )

            if settings.removed or not settings.enabled:
                self._outcome("disabled")
                return True
            if command_unavailable_reason(definition, services) is not None:
                self._outcome("ai_unavailable")
                return True

            if self._runtime_state is not None and not self._runtime_state.command_stream_available(settings.stream_availability):
                self._outcome("availability")
                return True

            maximum = self._max_arguments_length
            if definition.requires_ai:
                from app.config.ai_setup import effective_ai_setup
                maximum = effective_ai_setup(getattr(services, "settings", None)).max_question_length
            argument_length = len(arguments.strip()) if definition.requires_ai else len(arguments)
            if argument_length > maximum:
                self._outcome("invalid_arguments", reason="too_long")
                return True

            if definition.silent_invalid_arguments and (
                definition.argument_validator is not None
                and not definition.argument_validator(arguments)
            ):
                self._outcome("invalid_arguments")
                return True

            if not has_permission(message.author, max(settings.permission, definition.minimum_permission)):
                self._outcome("permissions")
                return True

            if (
                definition.argument_validator is not None
                and not definition.argument_validator(arguments)
            ):
                self._outcome("invalid_arguments")
                await definition.handler(
                    CommandContext(
                        message=message,
                        services=services,
                        logger=self._logger,
                        output_limiter=command_output_limiter,
                        burst_interval_ms=settings.burst_interval_ms,
                        burst_max_count=settings.burst_max_count,
                    ),
                    arguments,
                )
                operator_event(self._logger, "command.complete", "handler_completed")
                return True

            # Run pre-check if defined
            if definition.pre_check is not None:
                if not definition.pre_check(
                    CommandContext(
                        message=message,
                        services=services,
                        logger=self._logger,
                        output_limiter=command_output_limiter,
                        burst_interval_ms=settings.burst_interval_ms,
                        burst_max_count=settings.burst_max_count,
                    ),
                    arguments
                ):
                    # Pre-check failed - return immediately without cooldown
                    if not definition.requires_ai:
                        self._outcome("invalid_arguments")
                    return True

            # Check if this is the ask command and user has bypass permission
            should_skip_cooldown = False
            if definition.name == "ask" and self._ai_cooldown_bypass_user_id is not None:
                if message.author.twitch_user_id == self._ai_cooldown_bypass_user_id:
                    should_skip_cooldown = True

            # Only perform cooldown check if not bypassed
            if not should_skip_cooldown:
                cooldown = self._cooldowns.check_and_record(
                    command_name=cooldown_key,
                    user_id=message.author.twitch_user_id,
                    policy=settings.cooldown,
                )
                if not cooldown.allowed:
                    self._logger.info(
                        "Command cooldown rejected command=%s user=%s "
                        "retry_after_seconds=%.2f",
                        definition.name,
                        message.author.username,
                        cooldown.retry_after,
                        extra=event_metadata("command.cooldown", outcome="cooldown",
                                             retry_after_seconds=round(cooldown.retry_after, 2)),
                    )
                    return True

            self._logger.info(
                "Executing command name=%s user=%s",
                definition.name,
                message.author.username,
                extra=event_metadata("command.invoke", outcome="executing"),
            )
            await definition.handler(
                CommandContext(
                    message=message,
                    services=services,
                    logger=self._logger,
                    output_limiter=command_output_limiter,
                    burst_interval_ms=settings.burst_interval_ms,
                    burst_max_count=settings.burst_max_count,
                ),
                arguments,
            )
            operator_event(self._logger, "command.complete", "handler_completed")
            return True
        except Exception as error:
            self._logger.error("Command dispatch failed: %s", type(error).__name__,
                               extra=event_metadata("command.outcome", outcome="handler_failed",
                                                    error_type=type(error).__name__,
                                                    stage="send_session" if isinstance(error, ChatSessionClosedError)
                                                    else "dispatch_handler"))
            return True
