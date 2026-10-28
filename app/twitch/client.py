"""TwitchIO adapter that delegates chat behavior to application services."""

import asyncio
import logging
import json
import os
import secrets
import tempfile
from contextlib import contextmanager
from collections.abc import Callable
from pathlib import Path
from time import monotonic

from aiohttp import web

from twitchio import ChatMessage, Scopes, eventsub
from twitchio.authentication import UserTokenPayload
from twitchio.exceptions import HTTPException, InvalidTokenException
from twitchio.ext import commands
from twitchio.payloads import TokenRefreshedPayload
from twitchio.web import AiohttpAdapter
from sqlalchemy.exc import SQLAlchemyError

from app.commands.registry import CommandDispatcher
from app.config.settings import Settings, TwitchAccountSettings
from app.runtime_state import TwitchConnectionState
from app.services.facade import ApplicationServices
from app.services.ai_request_policy import PolicyDecision
from app.twitch.events import ChatAuthor, IncomingChatMessage
from app.twitch.message_correlation import ChatMessageCorrelation
from app.twitch.sending import ChatSendSession
from app.utils.text import parse_command
from app.utils.logging import privacy_log_scope, operator_event_scope, operator_event, event_metadata


class TwitchConnectionError(RuntimeError):
    """A Twitch connection failure that is safe to expose at the application boundary."""


OAUTH_REDIRECT_URI = "http://localhost:4343/oauth/callback"
CHAT_SCOPES = Scopes(["user:read:chat", "user:write:chat", "user:bot", "moderator:read:followers"])
# New consent includes highlighted sending; existing base-chat grants remain valid.
OAUTH_SCOPES = Scopes([*CHAT_SCOPES.selected, "moderator:manage:announcements"])
OAUTH_STATE_TTL_SECONDS = 300.0


def validate_bot_authorization(token, settings: Settings) -> None:
    """Verify server authorization before subscription or cache activation."""
    if (token.client_id != settings.twitch_client_id
            or token.user_id != settings.twitch_bot_user_id
            or (token.login or "").lower() != settings.twitch_bot_username.lower()
            or not set(CHAT_SCOPES.selected).issubset(token.scopes)):
        raise TwitchConnectionError("Twitch authorization does not match the configured application, bot account or required scopes. Authorize again from Settings.")


@contextmanager
def headless_twitch_diagnostics(on_failure: Callable[[], None]):
    """Observe library failures without rendering requests, tokens or payloads."""
    class FailureHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            if record.levelno >= logging.ERROR:
                on_failure()

    library_logger = logging.getLogger("twitchio")
    old_level, old_propagate = library_logger.level, library_logger.propagate
    handler = FailureHandler(level=logging.ERROR)
    library_logger.addHandler(handler)
    library_logger.setLevel(logging.ERROR)
    library_logger.propagate = False
    try:
        yield
    finally:
        library_logger.removeHandler(handler)
        library_logger.setLevel(old_level)
        library_logger.propagate = old_propagate


class DesktopOAuthAdapter(AiohttpAdapter):
    """Bind TwitchIO's existing code exchange to one explicit desktop attempt."""

    def __init__(self, *, clock: Callable[[], float] = monotonic, **kwargs) -> None:
        self._clock = clock
        self._pending_state: tuple[str, float] | None = None
        super().__init__(**kwargs)

    def begin_authorization(self) -> str:
        state = secrets.token_urlsafe(32)
        payload = self.client.http.get_authorization_url(
            scopes=OAUTH_SCOPES,
            state=state,
            redirect_uri=OAUTH_REDIRECT_URI,
            force_verify=True,
        )
        self._pending_state = (state, self._clock() + OAUTH_STATE_TTL_SECONDS)
        return payload["url"]

    async def oauth_redirect(self, request: web.Request) -> web.Response:
        # A public HTTP request must never create a pending desktop attempt.
        return web.Response(status=403, text="Start Twitch authorization from HeetKit.")

    async def oauth_callback(self, request: web.Request) -> web.Response:
        pending = self._pending_state
        if pending is None:
            return web.Response(status=400, text="No pending authorization attempt.")
        expected, expires_at = pending
        if self._clock() >= expires_at:
            self._pending_state = None
            return web.Response(status=400, text="Authorization attempt expired. Try again from HeetKit.")
        values = request.query.getall("state", [])
        if len(values) != 1 or not values[0].isascii() or not secrets.compare_digest(expected, values[0]):
            return web.Response(status=400, text="Invalid authorization state.")
        # Consume before token exchange yields, including denial/error callbacks.
        self._pending_state = None
        return await super().oauth_callback(request)

    async def close(self, *args, **kwargs) -> None:
        self._pending_state = None
        await super().close(*args, **kwargs)


def to_incoming_chat_message(message: ChatMessage, respond=None, send_session=None) -> IncomingChatMessage:
    """Map a TwitchIO chat event to the transport-neutral command DTO."""

    return IncomingChatMessage(
        channel=message.broadcaster.name,
        content=message.text,
        author=ChatAuthor(
            twitch_user_id=str(message.chatter.id),
            username=message.chatter.name,
            is_subscriber=bool(message.chatter.subscriber),
            is_vip=bool(message.chatter.vip),
            is_moderator=bool(message.chatter.moderator),
            is_broadcaster=bool(message.chatter.broadcaster),
            is_bot=any(getattr(badge, "set_id", None) == "bot" for badge in (getattr(message.chatter, "badges", None) or ())),
        ),
        respond=respond or message.respond,
        message_id=getattr(message, "id", None),
        send_session=send_session,
    )


async def process_twitch_message(
    message: ChatMessage,
    services: ApplicationServices,
    dispatcher: CommandDispatcher,
    logger: logging.Logger,
    correlation: ChatMessageCorrelation | None = None,
    send_session: ChatSendSession | None = None,
) -> None:
    """Persist the chatter and route a mapped Twitch event to the dispatcher."""

    try:
        account = getattr(getattr(services, "settings", None), "twitch_bot_user_id", None)
        channel = str(getattr(message.broadcaster, "id", message.broadcaster.name))
        if correlation is not None and str(message.chatter.id) == account:
            if await correlation.is_outgoing(account, channel,
                    (getattr(message, "id", None), getattr(message, "source_id", None))):
                return
        async def respond(content):
            return await correlation.send(account, channel, message.respond, content)
        incoming = to_incoming_chat_message(message, respond if correlation is not None else None, send_session)
    except (AttributeError, TypeError):
        logger.exception("Could not map incoming Twitch chat message")
        return

    opted_out = False
    privacy_check = getattr(services.users, "is_storage_opted_out", None)
    if privacy_check is not None:
        try:
            opted_out = await privacy_check(incoming.author.twitch_user_id)
        except Exception as error:
            # Keep commands working, but fail closed for personal diagnostics.
            opted_out = True
            logger.error("Could not check storage opt-out: %s", type(error).__name__)
    with privacy_log_scope(opted_out):
        try:
            scope = getattr(dispatcher, "event_scope", None)
            with (scope(incoming) if scope else operator_event_scope(
                    channel=incoming.channel, username=incoming.author.username,
                    input_message_id=incoming.message_id)):
                await _process_incoming_message(incoming, services, dispatcher, logger)
        except Exception:
            if not opted_out:
                raise
            # An outer transport exception logger must not expose private input.
            logger.error("Unexpected opted-out chat processing failure")


async def _process_incoming_message(
    incoming: IncomingChatMessage,
    services: ApplicationServices,
    dispatcher: CommandDispatcher,
    logger: logging.Logger,
) -> None:

    # Reject blocked Ask accounts before filters, content logging, user writes or AI work.
    if getattr(services, "ai_user_blocks", None) is not None and dispatcher.is_ai_request_blocked(incoming, services):
        return

    # Check if message should be filtered out
    if not services.filter_manager.filter_message(incoming.content):
        operator_event(logger, "chat.filtered", "filters", inherit_context=False,
                       source="filter", reason="content_filter")
        return

    # Decide before recording request content; ignored AI input must stay out of
    # chat logs and memory just like input rejected by profile filters.
    prefix = getattr(getattr(services, "settings", None), "command_prefix", "!")
    parsed = parse_command(incoming.content, prefix)
    policy = getattr(services, "ai_request_policy", None)
    is_ai = getattr(dispatcher, "is_ai_command", lambda _: parsed is not None and parsed[0] == "ask")
    if parsed is not None and is_ai(incoming) and policy is not None:
        if policy.check(parsed[1]) == PolicyDecision.IGNORE:
            operator_event(logger, "command.outcome", "filters", reason="protected_policy")
            return

    twitch = getattr(services, "twitch", None)
    if twitch is not None:
        twitch.record_human_message(incoming)

    try:
        await services.users.upsert_seen(
            twitch_user_id=incoming.author.twitch_user_id,
            username=incoming.author.username,
        )
    except SQLAlchemyError:
        logger.exception("Could not persist chat user")
    except Exception:
        logger.exception("Unexpected user persistence failure")

    try:
        await dispatcher.dispatch(incoming, services)
    except Exception:
        logger.exception("Unexpected command dispatcher failure")


class TwitchChatBot(commands.Bot):
    def __init__(
        self,
        settings: Settings,
        account: TwitchAccountSettings,
        services: ApplicationServices,
        dispatcher: CommandDispatcher,
        logger: logging.Logger,
    ) -> None:
        settings.validate_twitch_configuration()
        assert settings.twitch_client_secret is not None
        self._account = account
        self._services = services
        self._dispatcher = dispatcher
        self._logger = logger
        self._token_file = Path(settings.twitch_token_file)
        self._active_socket_id: str | None = None
        self._closing_requested = False
        self._chat_messages = getattr(services.twitch, "chat_messages", None) or ChatMessageCorrelation()
        self._token_save_lock = asyncio.Lock()
        self._tokens_loaded = False
        self._loading_tokens = False
        self._cached_tokens: dict[str, dict] = {}
        self._close_lock = asyncio.Lock()
        self._closing_task: asyncio.Task | None = None
        self._close_save_failed = False
        self.require_verified_identity = False
        self._settings = settings
        super().__init__(
            client_id=settings.twitch_client_id,
            client_secret=settings.twitch_client_secret.get_secret_value(),
            bot_id=account.user_id,
            prefix=settings.command_prefix,
            redirect_uri=OAUTH_REDIRECT_URI,
            scopes=OAUTH_SCOPES,
            adapter=DesktopOAuthAdapter(host="localhost", port=4343),
        )
        if services.twitch is not None:
            services.twitch.bind(self, account.channel_user_id, account.user_id, channel_name=account.channel)

    def _set_connection_state(self, state: TwitchConnectionState) -> None:
        if self._services.twitch is not None:
            self._services.twitch.set_chat_ready(self, state == "connected" and not self._closing_requested)
        runtime_state = getattr(self._services, "runtime_state", None)
        if runtime_state is not None:
            runtime_state.set_twitch_connection_state(state)

    def begin_authorization(self) -> str:
        state = self._services.runtime_state
        if self._closing_requested or state is None or not state.status()[0] or state.twitch_connection_state not in ("auth_required", "connected"):
            raise ValueError("Twitch authorization is not currently required.")
        return self.adapter.begin_authorization()

    async def close(self, *args, **kwargs) -> None:
        async with self._close_lock:
            if self._closing_requested:
                return
            self._closing_requested = True
            self._closing_task = asyncio.current_task()
            # TwitchIO stops refresh work, saves, then clears managed tokens. Only
            # this close task may save now; queued refresh listeners must not later
            # replace the persisted cache with the cleared in-memory dictionary.
            try:
                try:
                    if self._services.twitch is not None:
                        await self._services.twitch.unbind(self)
                finally:
                    await super().close(*args, **{**kwargs, "save_tokens": self._tokens_loaded})
            finally:
                self._closing_task = None
            if self._close_save_failed:
                raise TwitchConnectionError("Could not persist Twitch authorization during shutdown.")

    async def event_error(self, payload: object) -> None:
        self._set_connection_state("failed")
        self._logger.error(
            "Twitch asynchronous operation failed; session must be restarted",
            extra={"event_kind": "twitch.failed"},
        )

    async def setup_hook(self) -> None:
        if self.bot_id not in self.tokens:
            if self.require_verified_identity:
                self._set_connection_state("auth_required")
            self._logger.info("Waiting for Twitch bot OAuth authorization")
            return
        await self._subscribe_to_chat()

    async def _subscribe_to_chat(self) -> None:
        self._logger.info(
            "Subscribing to Twitch chat channel=%s",
            self._account.channel,
            extra={
                "event_kind": "twitch.subscribe",
                "event_channel": self._account.channel,
            },
        )
        subscription = eventsub.ChatMessageSubscription(
            broadcaster_user_id=self._account.channel_user_id,
            user_id=self._account.user_id,
        )
        await self.subscribe_websocket(payload=subscription, as_bot=True)

    async def event_ready(self) -> None:
        if self.bot_id not in self.tokens:
            self._set_connection_state("auth_required")
            self._logger.warning(
                "Authorize the configured bot account using Authorize Twitch in HeetKit",
                extra={"event_kind": "twitch.auth_required", "event_channel": self._account.channel},
            )
            return
        self._set_connection_state("connected")
        self._logger.info(
            "Twitch connection ready account=%s channel=%s",
            self._account.username,
            self._account.channel,
            extra={
                "event_kind": "twitch.connected",
                "event_username": self._account.username,
                "event_channel": self._account.channel,
            },
        )

    async def event_oauth_authorized(self, payload: UserTokenPayload) -> None:
        token = await self.add_token(payload["access_token"], payload["refresh_token"])
        if token.user_id == self.bot_id:
            self._tokens_loaded = True
            self._cached_tokens = {}
            await self.save_tokens()
            self._logger.info("Configured bot account OAuth authorization completed")
            if not (self._services.twitch is not None and self._services.twitch.chat_connected):
                await self._subscribe_to_chat()
            self._set_connection_state("connected")
            return

        if token.user_id == self._account.channel_user_id:
            await self.remove_token(token.user_id)
            self._logger.info("Configured channel OAuth authorization completed")
            return

        await self.remove_token(token.user_id)
        self._set_connection_state("auth_required")
        self._logger.error(
            "OAuth authorization was for an unknown account",
            extra={"event_kind": "twitch.auth_required", "event_channel": self._account.channel},
        )

    async def event_token_refreshed(self, payload: TokenRefreshedPayload) -> None:
        if payload.user_id == self.bot_id:
            await self.save_tokens()
            self._logger.info("Configured bot account token refreshed")

    async def load_tokens(self, path: str | None = None, /) -> None:
        try:
            with self._token_file.open(encoding="utf-8") as stream:
                cached = json.load(stream)
        except FileNotFoundError:
            return
        # Validate the whole cache before refreshing anything. A malformed later
        # record must not strand an earlier, already rotated refresh token.
        if not isinstance(cached, dict) or any(
            not isinstance(record, dict) or any(
                not isinstance(record.get(field), str) or not record[field]
                for field in ("token", "refresh")
            ) for record in cached.values()
        ):
            raise TwitchConnectionError("Twitch authorization cache is malformed; restore a private backup or reauthorize.")
        self._cached_tokens = cached
        self._tokens_loaded = True
        self._loading_tokens = True
        try:
            for record in cached.values():
                try:
                    # TwitchIO retains validation/refresh ownership. Persist only
                    # its managed result, never construct or refresh tokens here.
                    validated = await self.add_token(record["token"], record["refresh"])
                    if self.require_verified_identity:
                        try:
                            validate_bot_authorization(validated, self._settings)
                        except TwitchConnectionError:
                            if validated.user_id:
                                await self.remove_token(validated.user_id)
                            continue
                        users = await self.fetch_users(ids=[self._account.channel_user_id], token_for=self.bot_id)
                        if not any(str(user.id) == self._account.channel_user_id and
                                   user.name.lower() == self._account.channel.lower() for user in users):
                            raise TwitchConnectionError("Configured Twitch channel does not match its account ID. Correct Settings before reconnecting.")
                except InvalidTokenException:
                    continue
            if self.bot_id in self.tokens:
                self._cached_tokens = {}
        finally:
            self._loading_tokens = False
            # On partial failure retain untouched original records alongside any
            # validated/rotated tokens; never lose a rotation from this attempt.
            if self.tokens:
                await self.save_tokens()

    async def save_tokens(self, path: str | None = None, /) -> None:
        if self._loading_tokens or not self._tokens_loaded or (
            self._closing_requested and asyncio.current_task() is not self._closing_task
        ):
            return
        async with self._token_save_lock:
            try:
                await self._save_tokens_atomically()
            except TwitchConnectionError:
                if not self._closing_requested:
                    raise
                # Let TwitchIO finish resource cleanup and unblock start before
                # close reports the failure to the application.
                self._close_save_failed = True

    async def _save_tokens_atomically(self) -> None:
        temporary: Path | None = None
        try:
            self._token_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            # mkstemp is exclusive and creates 0600 before any secret bytes exist.
            descriptor, name = tempfile.mkstemp(dir=self._token_file.parent, suffix=".tmp")
            temporary = Path(name)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(self._cached_tokens | self.tokens, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self._token_file)
        except Exception as error:
            self._set_connection_state("failed")
            self._logger.error(
                "Could not persist Twitch authorization; check private profile storage and reauthorize if needed error_type=%s",
                type(error).__name__,
                extra={"event_kind": "twitch.failed"},
            )
            raise TwitchConnectionError("Could not persist Twitch authorization.") from None
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    self._logger.error("Could not remove private token staging file", extra={"event_kind": "twitch.failed"})

    async def event_message(self, message: ChatMessage) -> None:
        # EventSub delivery is not an exactly-once command invocation. Reserve
        # the stable chat ID before any await so concurrent replays cannot send
        # another batch, even when the command has no cooldown.
        message_id = getattr(message, "id", None)
        channel = str(getattr(message.broadcaster, "id", message.broadcaster.name))
        if not self._chat_messages.reserve(self.bot_id, channel, message_id):
            return
        try:
            await process_twitch_message(
                message=message,
                services=self._services,
                dispatcher=self._dispatcher,
                logger=self._logger,
                correlation=self._chat_messages,
                send_session=(self._services.twitch.chat_session(self)
                              if self._services.twitch is not None else None),
            )
        except Exception:
            self._logger.exception("Unexpected Twitch message processing failure")

    async def event_websocket_welcome(self, payload: object) -> None:
        self._active_socket_id = getattr(payload, "id", None)
        if self.bot_id not in self.tokens or self._closing_requested:
            return
        runtime_state = getattr(self._services, "runtime_state", None)
        state = runtime_state.twitch_connection_state if runtime_state is not None else None
        if state == "reconnecting":
            self._set_connection_state("connected")
            self._logger.info(
                "Twitch chat connection recovered channel=%s",
                self._account.channel,
                extra={"event_kind": "twitch.recovered", "event_channel": self._account.channel},
            )

    async def event_subscription_revoked(self, payload: object) -> None:
        if getattr(payload, "type", None) != "channel.chat.message":
            return
        reason = getattr(getattr(payload, "status", None), "value", "unknown")
        state: TwitchConnectionState = (
            "auth_required"
            if reason in ("authorization_revoked", "user_removed", "chat_user_banned")
            else "failed"
        )
        self._set_connection_state(state)
        self._logger.error(
            "Twitch chat subscription revoked reason=%s channel=%s",
            reason,
            self._account.channel,
            extra={
                "event_kind": "twitch.auth_required" if state == "auth_required" else "twitch.failed",
                "event_channel": self._account.channel,
            },
        )

    async def event_websocket_closed(self, payload: object) -> None:
        if self._closing_requested:
            return
        runtime_state = getattr(self._services, "runtime_state", None)
        if runtime_state is not None and runtime_state.twitch_connection_state in (
            "auth_required", "failed"
        ):
            return
        socket_id = getattr(getattr(payload, "socket", None), "session_id", None)
        # Failed SDK reconnect candidates also emit close, without ever receiving
        # a welcome/session ID. They do not own the current sending connection.
        if self._active_socket_id is not None and socket_id != self._active_socket_id:
            operator_event(self._logger, "twitch.socket", "close_ignored", inherit_context=False,
                           reason="unwelcomed_socket" if socket_id is None else "superseded_socket",
                           stage="connection_lifecycle", source="lifecycle")
            return
        self._set_connection_state("reconnecting")
        self._logger.warning(
            "Twitch chat connection closed; TwitchIO is handling recovery channel=%s",
            self._account.channel,
            extra={
                "event_kind": "twitch.disconnected",
                "event_channel": self._account.channel,
            },
        )


async def run_twitch_bot(
    settings: Settings,
    services: ApplicationServices,
    dispatcher: CommandDispatcher,
    logger: logging.Logger,
    stop_event: asyncio.Event | None = None,
    *,
    headless: bool = False,
) -> None:
    settings.validate_twitch_configuration()
    account = settings.primary_account
    bot = TwitchChatBot(
        settings=settings,
        account=account,
        services=services,
        dispatcher=dispatcher,
        logger=logger,
    )
    bot.require_verified_identity = headless
    stop_task: asyncio.Task[None] | None = None
    monitor_task: asyncio.Task[None] | None = None

    def terminal_failure(state: TwitchConnectionState, message: str) -> None:
        twitch = getattr(services, "twitch", None)
        if twitch is not None:
            twitch.set_chat_ready(bot, False)
        runtime_state = getattr(services, "runtime_state", None)
        if runtime_state is not None:
            runtime_state.set_twitch_connection_state(state)
        logger.error(
            message,
            extra={
                "event_kind": "twitch.auth_required" if state == "auth_required" else "twitch.failed",
                "event_channel": account.channel,
            },
        )

    async def close_when_requested() -> None:
        if stop_event is None:
            return
        await stop_event.wait()
        await bot.close(save_tokens=False)

    async def monitor_authorization() -> None:
        while True:
            await asyncio.sleep(0.2)
            runtime_state = services.runtime_state
            if runtime_state.twitch_connection_state in ("connected", "reconnecting") and account.user_id not in bot.tokens:
                terminal_failure("auth_required", "Twitch authorization expired or was revoked; reauthorize using the desktop")

    def background_failure() -> None:
        terminal_failure("failed", "Twitch background connection operation failed; check authorization/network and restart")

    try:
        if stop_event is not None:
            stop_task = asyncio.create_task(close_when_requested())
        if headless:
            monitor_task = asyncio.create_task(monitor_authorization())
            with headless_twitch_diagnostics(background_failure):
                await bot.start(with_adapter=False, load_tokens=True, save_tokens=True)
        else:
            await bot.start(with_adapter=True, load_tokens=True, save_tokens=True)
    except asyncio.CancelledError:
        logger.info(
            "Twitch client shutdown requested",
            extra={
                "event_kind": "twitch.shutdown",
                "event_channel": account.channel,
            },
        )
        raise
    except InvalidTokenException as error:
        terminal_failure("auth_required", "Twitch user token validation failed; authorization required")
        logger.error(
            "Twitch user token validation failed status=%s invalid_type=%s",
            error.status,
            error.invalid_type,
        )
        raise TwitchConnectionError("Twitch user token validation failed.") from None
    except HTTPException as error:
        state: TwitchConnectionState = "auth_required" if error.status in (401, 403) else "failed"
        terminal_failure(state, "Twitch API request failed; session stopped")
        logger.error("Twitch API failure status=%s error_type=%s", error.status, type(error).__name__)
        raise TwitchConnectionError("Twitch API request failed.") from None
    except OSError as error:
        terminal_failure("failed", "Twitch network connection failed; session stopped")
        logger.error("Twitch network failure error_type=%s", type(error).__name__)
        raise TwitchConnectionError("Twitch network connection failed.") from None
    except Exception as error:
        terminal_failure("failed", "Unexpected Twitch client failure; session stopped")
        logger.error("Twitch client failure error_type=%s", type(error).__name__)
        raise TwitchConnectionError("Twitch client startup failed.") from None
    finally:
        if monitor_task is not None:
            monitor_task.cancel()
            try:
                await monitor_task
            except asyncio.CancelledError:
                pass
        if stop_task is not None:
            stop_task.cancel()
            try:
                await stop_task
            except asyncio.CancelledError:
                pass
        try:
            await bot.close(save_tokens=False)
        except Exception as error:
            logger.error("Twitch client shutdown failed error_type=%s", type(error).__name__)
            if headless:
                raise TwitchConnectionError("Twitch client shutdown failed; verify private token storage.") from None
