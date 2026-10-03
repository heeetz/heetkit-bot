"""Declarative command registration and fault-isolated dispatching."""

import logging
import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from app.command_settings import CommandSettings
from app.custom_commands import CustomCommand, CustomCommandStore, render_response
from app.message_triggers import MessageTriggerStore
from app.runtime_state import RuntimeState
from app.services.facade import ApplicationServices
from app.twitch.events import IncomingChatMessage
from app.twitch.permissions import Permission, has_permission
from app.utils.cooldown import CooldownManager, CooldownPolicy
from app.utils.output_limiter import OutputLimiter
from app.utils.text import normalize_command_name, parse_command


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

    @property
    def default_settings(self) -> CommandSettings:
        return CommandSettings(
            enabled=self.enabled_by_default,
            cooldown=self.cooldown,
            permission=self.required_permission,
        )


@dataclass(frozen=True, slots=True)
class CommandContext:
    message: IncomingChatMessage
    services: ApplicationServices
    logger: logging.Logger
    output_limiter: OutputLimiter | None = None

    async def reply(self, content: str) -> bool:
        if self.output_limiter is not None and not self.output_limiter.try_acquire():
            return False
        try:
            await self.message.respond(content)
            self.logger.info(
                "Outgoing bot response channel=%s user=%s length=%d",
                self.message.channel,
                self.message.author.username,
                len(content),
                extra={
                    "event_kind": "chat.outgoing",
                    "event_channel": self.message.channel,
                    "event_username": self.message.author.username,
                },
            )
            return True
        except Exception:
            self.logger.exception(
                "Could not send command response user=%s",
                self.message.author.username,
            )
            raise

    async def reply_burst(
        self,
        content: str,
        count: int,
        delay: float = 1.0,
    ) -> None:
        for i in range(count):
            await self.reply(content)
            if i < count - 1:
                await asyncio.sleep(delay)


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

    def help_entries(self) -> tuple[str, ...]:
        return tuple(
            definition.help_text or f"!{definition.name}"
            for definition in self.definitions()
            if not definition.hidden
        )


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

    async def _dispatch_trigger(self, message: IncomingChatMessage, services: ApplicationServices) -> bool:
        if self._message_triggers is None or message.author.twitch_user_id == services.settings.twitch_bot_user_id:
            return False
        for trigger in self._message_triggers.list():
            if not trigger.enabled or not trigger.matches(message.content):
                continue
            if random.random() >= trigger.probability:
                continue
            cooldown = self._cooldowns.check_and_record(
                command_name=f"trigger:{trigger.id}",
                user_id=message.author.twitch_user_id,
                policy=CooldownPolicy(global_seconds=trigger.cooldown_seconds),
            )
            if not cooldown.allowed:
                continue
            response = random.choice(trigger.responses)
            await CommandContext(message, services, self._logger, self._output_limiter).reply(response)
            return True
        return False

    async def _run_custom_command(self, command: CustomCommand, context: CommandContext, arguments: str) -> None:
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
            await context.reply(response)

    async def dispatch(self, message: IncomingChatMessage, services: ApplicationServices) -> bool:
        try:
            parsed_command = parse_command(message.content, self._command_prefix)
            if parsed_command is None:
                if message.content.strip().startswith(self._command_prefix):
                    return False
                return await self._dispatch_trigger(message, services)

            command_name, arguments = parsed_command
            definition = self._registry.get(command_name)
            custom = None
            if definition is None:
                custom = None if self._custom_commands is None else self._custom_commands.get_by_name(command_name)
                if custom is None:
                    return False
                async def custom_handler(context: CommandContext, tail: str) -> None:
                    await self._run_custom_command(custom, context, tail)
                definition = CommandDefinition(name=custom.name, handler=custom_handler)
                settings = CommandSettings(enabled=custom.enabled, permission=custom.permission, cooldown=custom.cooldown)
            else:
                settings = (
                    definition.default_settings
                    if self._runtime_state is None
                    else self._runtime_state.get_command_settings(definition.name)
                )
            cooldown_key = f"custom:{custom.id}" if custom is not None else definition.name

            command_output_limiter = (
                None if definition.name == "tg" else self._output_limiter
            )

            if not settings.enabled:
                return True

            if len(arguments) > self._max_arguments_length:
                return True

            if definition.silent_invalid_arguments and (
                definition.argument_validator is not None
                and not definition.argument_validator(arguments)
            ):
                return True

            if not has_permission(message.author, settings.permission):
                return True

            if (
                definition.argument_validator is not None
                and not definition.argument_validator(arguments)
            ):
                await definition.handler(
                    CommandContext(
                        message=message,
                        services=services,
                        logger=self._logger,
                        output_limiter=command_output_limiter,
                    ),
                    arguments,
                )
                return True

            # Run pre-check if defined
            if definition.pre_check is not None:
                if not definition.pre_check(
                    CommandContext(
                        message=message,
                        services=services,
                        logger=self._logger,
                        output_limiter=command_output_limiter,
                    ),
                    arguments
                ):
                    # Pre-check failed - return immediately without cooldown
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
                        extra={
                            "event_kind": "command.cooldown",
                            "event_command": definition.name,
                            "event_username": message.author.username,
                            "event_retry_after_seconds": round(
                                cooldown.retry_after,
                                2,
                            ),
                        },
                    )
                    return True

            self._logger.info(
                "Executing command name=%s user=%s",
                definition.name,
                message.author.username,
                extra={
                    "event_kind": "command.invoke",
                    "event_command": definition.name,
                    "event_username": message.author.username,
                    "event_channel": message.channel,
                },
            )
            await definition.handler(
                CommandContext(
                    message=message,
                    services=services,
                    logger=self._logger,
                    output_limiter=command_output_limiter,
                ),
                arguments,
            )
            return True
        except Exception:
            self._logger.exception("Command dispatch failed")
            return True
