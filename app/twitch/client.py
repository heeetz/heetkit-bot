"""TwitchIO adapter that delegates chat behavior to application services."""

import asyncio
import logging
import json
import os
import errno
import secrets
import tempfile
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from collections.abc import Callable
import hashlib
from pathlib import Path
from time import monotonic, time as wall_time
from math import isfinite
from email.utils import parsedate_to_datetime

from aiohttp import web, ClientError, ClientResponseError
from datetime import datetime
from random import uniform

from twitchio import ChatMessage, Scopes, eventsub
from twitchio.authentication import UserTokenPayload
from twitchio.exceptions import HTTPException, InvalidTokenException, WebsocketConnectionException
from twitchio.ext import commands
from twitchio.payloads import TokenRefreshedPayload
from twitchio.web import AiohttpAdapter
from sqlalchemy.exc import SQLAlchemyError

from app.commands.registry import CommandContext, CommandDispatcher
from app.config.settings import Settings, TwitchAccountSettings
from app.config.privacy import PRIVACY_COMMAND
from app.runtime_state import TwitchConnectionState
from app.services.facade import ApplicationServices
from app.services.ai_request_policy import PolicyDecision
from app.twitch.events import ChatAuthor, IncomingChatMessage
from app.twitch.message_correlation import ChatMessageCorrelation
from app.twitch.sending import ChatSendSession, ChatSessionClosedError
from app.twitch.socket import OwnedWebsocket
from app.utils.text import parse_command
from app.utils.logging import privacy_log_scope, operator_event_scope, operator_event, event_metadata
from app.analytics import analytics_scope_for


class TwitchConnectionError(RuntimeError):
    """A Twitch connection failure that is safe to expose at the application boundary."""


class TwitchCleanupError(TwitchConnectionError):
    """Ownership could not be released; do not allow another client to start."""


# SDK backoff caps at 90s, welcome waits 11s, default keepalive is 10s (+5s
# SDK tolerance). Leave time for a normal retry and subscription HTTP completion.
RECOVERY_DEADLINE = 120.0
RECOVERY_POLL = 1.0
CLEANUP_DEADLINE = 15.0
BACKOFF_BASE = 5.0
BACKOFF_CAP = 120.0
STABLE_RESET = 300.0


OAUTH_REDIRECT_URI = "http://localhost:4343/oauth/callback"
CHAT_SCOPES = Scopes(["user:read:chat", "user:write:chat", "user:bot", "moderator:read:followers"])
# New consent includes highlighted sending; existing base-chat grants remain valid.
OAUTH_SCOPES = Scopes([*CHAT_SCOPES.selected, "moderator:manage:announcements"])
OAUTH_STATE_TTL_SECONDS = 300.0
_transport_origin: ContextVar[str | None] = ContextVar("twitch_transport_origin", default=None)
_dispatch_origin: ContextVar[tuple | None] = ContextVar("twitch_dispatch_origin", default=None)
_socket_event: ContextVar[tuple | None] = ContextVar("twitch_socket_event", default=None)


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


@contextmanager
def twitch_lifecycle_diagnostics(on_record):
    """Keep SDK requests/payloads private while retaining typed lifecycle failures."""
    class Handler(logging.Handler):
        def emit(self, record):
            on_record(record)
    sdk_logger = logging.getLogger("twitchio")
    old_level, old_propagate = sdk_logger.level, sdk_logger.propagate
    handler = Handler(level=logging.ERROR)
    sdk_logger.addHandler(handler)
    sdk_logger.setLevel(logging.ERROR)
    sdk_logger.propagate = False
    try:
        yield
    finally:
        sdk_logger.removeHandler(handler)
        sdk_logger.setLevel(old_level)
        sdk_logger.propagate = old_propagate


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
        channel_id=str(getattr(message.broadcaster, "id", "")),
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

    storage_scope = getattr(services.users, "storage_scope", None)
    with storage_scope(incoming.author.twitch_user_id) if storage_scope else nullcontext():
        prefix = getattr(getattr(services, "settings", None), "command_prefix", "!")
        parsed = parse_command(incoming.content, prefix)
        if parsed is not None and parsed[0] == PRIVACY_COMMAND:
            # Replay reservation and echo correlation have already run. No personal
            # scope, command diagnostics, filters, block rules or cooldowns precede this.
            with privacy_log_scope(True):
                try:
                    await services.users.opt_out(incoming.author.twitch_user_id, username=incoming.author.username)
                    await CommandContext(incoming, services, logger).reply("Local data storage disabled. Fresh AI requests still reach the provider.")
                except Exception as error:
                    logger.error("Privacy request failed: %s", type(error).__name__)
                    await CommandContext(incoming, services, logger).reply("Privacy request could not complete. Contact the bot operator.")
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
        def suppress_logs():
            return opted_out or getattr(services.users, "logs_suppressed", lambda _: False)(incoming.author.twitch_user_id)
        with privacy_log_scope(suppress_logs), analytics_scope_for(services, incoming):
            try:
                scope = getattr(dispatcher, "event_scope", None)
                with (scope(incoming) if scope else operator_event_scope(
                        channel=incoming.channel, username=incoming.author.username,
                        input_message_id=incoming.message_id)):
                    outcome_scope = getattr(dispatcher, "outcome_scope", None)
                    with outcome_scope(incoming) if outcome_scope else nullcontext():
                        await _process_incoming_message(incoming, services, dispatcher, logger)
            except Exception:
                if not suppress_logs():
                    raise
                # An outer transport exception logger must not expose private input.
                logger.error("Unexpected opted-out chat processing failure")


async def _process_incoming_message(
    incoming: IncomingChatMessage,
    services: ApplicationServices,
    dispatcher: CommandDispatcher,
    logger: logging.Logger,
) -> None:

    # Privacy and replay/echo checks already ran. Restrict before input logging,
    # user writes, filters, cooldowns, providers and outgoing capacity.
    if (getattr(services, "command_restrictions", None) is not None
            and dispatcher.is_command_restricted(incoming, services)):
        return

    # Reject blocked Ask accounts before filters, content logging, user writes or AI work.
    if getattr(services, "ai_user_blocks", None) is not None and dispatcher.is_ai_request_blocked(incoming, services):
        return

    # Check if message should be filtered out
    if not services.filter_manager.filter_message(incoming.content):
        getattr(dispatcher, "skip_outcome", lambda _: None)("filters")
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
            getattr(dispatcher, "skip_outcome", lambda _: None)("filters")
            operator_event(logger, "command.outcome", "filters", reason="protected_policy")
            return

    twitch = getattr(services, "twitch", None)
    if twitch is not None:
        twitch.record_human_message(incoming)

    try:
        await services.users.upsert_seen(
            twitch_user_id=incoming.author.twitch_user_id,
            username=incoming.author.username,
            channel_id=incoming.channel_id,
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
        self._socket_sequence = 0
        self._last_socket_sequence = 0
        self._lifecycle_error: Exception | None = None
        self._had_authorization = False
        self._send_authorized = False
        self._retired = False
        self._owned_sockets: set = set()
        self._ingress_tasks: set[asyncio.Task] = set()
        self._event_tasks: set[asyncio.Task] = set()
        self._closing_requested = False
        self._diagnostic_id = secrets.token_hex(8)
        self._diagnostic_salt = secrets.token_bytes(16)
        self._message_dispatches = 0
        self._connection_notices: dict[str, tuple[float, int]] = {}
        self._chat_messages = getattr(services.twitch, "chat_messages", None) or ChatMessageCorrelation()
        self._token_save_lock = asyncio.Lock()
        self._tokens_loaded = False
        self._loading_tokens = False
        self._cached_tokens: dict[str, dict] = {}
        self._close_lock = asyncio.Lock()
        self._closing_task: asyncio.Task | None = None
        self._close_save_failed = False
        self._close_failure: TwitchCleanupError | None = None
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

    def _socket_ref(self, value: str | None) -> str | None:
        return (hashlib.blake2s(value.encode(), key=self._diagnostic_salt, digest_size=6).hexdigest()
                if isinstance(value, str) and value else None)

    async def _dispatch(self, listener, *, original=None):
        if not self._owns_session():
            return
        task = asyncio.current_task()
        self._event_tasks.add(task)
        try:
            await super()._dispatch(listener, original=original)
        finally:
            self._event_tasks.discard(task)

    def _registered_sockets(self):
        return self._owned_sockets | {socket for sockets in self._websockets.values() for socket in sockets.values()}

    def dispatch(self, event: str, payload=None) -> None:
        # SDK listener tasks carry the source socket name. Preserve only an
        # opaque per-client reference across SDK-created handler tasks.
        task = asyncio.current_task()
        name = task.get_name() if task is not None else ""
        prefix = "EventsubWebsocketListener: "
        origin = self._socket_ref(name[len(prefix):]) if name.startswith(prefix) else None
        token = _transport_origin.set(origin)
        snapshot = None
        if event in {"websocket_closed", "websocket_welcome"}:
            self._socket_sequence += 1
            # WebsocketClosed holds a mutable SDK socket reused on reconnect.
            # Capture its ID now, before the asynchronous handler can see a new ID.
            identifier = (getattr(payload, "id", None) if event == "websocket_welcome"
                          else getattr(getattr(payload, "socket", None), "session_id", None))
            snapshot = (self._socket_sequence, identifier)
        socket_token = _socket_event.set(snapshot)
        delivery = None
        if event.lower() == "message":
            self._message_dispatches += 1
            subscription = notification = None
            try:
                subscription = self._socket_ref(getattr(getattr(payload, "subscription_data", None), "id", None))
                notification = self._socket_ref(getattr(getattr(payload, "metadata", None), "message_id", None))
            except (AttributeError, KeyError, TypeError, ValueError):
                pass  # Missing SDK metadata affects diagnostics only.
            delivery = (self._message_dispatches, subscription, notification)
        delivery_token = _dispatch_origin.set(delivery)
        try:
            super().dispatch(event, payload)
        finally:
            _transport_origin.reset(token)
            _dispatch_origin.reset(delivery_token)
            _socket_event.reset(socket_token)

    def _owns_session(self) -> bool:
        if self._closing_requested or self._retired:
            return False
        if self._services.twitch is not None:
            try:
                self._services.twitch.chat_session(self)
            except ChatSessionClosedError:
                return False
            if self._services.twitch.chat_stopping:
                return False
        return True

    def refresh_readiness(self) -> bool:
        """Inspect protocol liveness and completed SDK subscriptions, never chat activity.

        TwitchIO 3.3.2 dispatches welcome before connect/_resubscribe finishes.
        Its socket registry keys can lag a reused socket's session ID; use values.
        """
        if not self._owns_session() or self._lifecycle_error is not None:
            return False
        runtime = getattr(self._services, "runtime_state", None)
        if runtime is not None and runtime.twitch_connection_state in {"failed", "auth_required"}:
            return False
        authorized = self.bot_id in self.tokens
        self._had_authorization |= authorized
        if not authorized:
            if self._had_authorization or (self.require_verified_identity and self._setup_called):
                self._set_connection_state("auth_required")
            return False
        if not self._send_authorized:
            self._set_connection_state("auth_required")
            return False
        usable = None
        for socket in self._registered_sockets():
            last = socket._last_keepalive
            if (not socket.connected or socket._connecting or not socket._ready.is_set()
                    or socket._listen_task is None or socket._listen_task.done()
                    or last is None or (datetime.now() - last).total_seconds() > socket.keep_alive_timeout + 5):
                continue
            if any(str(getattr(sub.get("type"), "value", sub.get("type"))) == "channel.chat.message"
                   and sub.get("condition", {}).get("broadcaster_user_id") == self._account.channel_user_id
                   and sub.get("condition", {}).get("user_id") == self.bot_id
                   for sub in socket._subscriptions.values()):
                usable = socket
                break
        if usable is not None:
            self._active_socket_id = usable.session_id
            if self._services.twitch is not None:
                self._services.twitch.set_chat_ready(self, True)
            if runtime is None or runtime.twitch_connection_state != "connected":
                recovering = runtime is not None and runtime.twitch_connection_state == "reconnecting"
                self._set_connection_state("connected")
                self._logger.info("Twitch usable chat session ready", extra={"event_kind": "twitch.recovered" if recovering else "twitch.connected"})
            return True
        if runtime is not None and runtime.twitch_connection_state == "connected":
            self._set_connection_state("reconnecting")
        return False

    def _connection_event(self, reason: str, *, socket_id: str | None = None) -> None:
        now = monotonic()
        last, count = self._connection_notices.get(reason, (float("-inf"), 0))
        self._connection_notices[reason] = (last, count + 1)
        repeated = reason in {"closed_client_ingress", "replaced_client_ingress", "inactive_session_ingress",
                              "unwelcomed_socket", "superseded_socket", "superseded_socket_ingress"}
        if repeated and now - last < 30:
            return
        self._connection_notices[reason] = (now, count + 1)
        twitch = self._services.twitch
        try:
            session = twitch.chat_session(self) if twitch is not None else None
            current = twitch is not None
        except ChatSessionClosedError:
            session, current = None, False
        sockets = self._registered_sockets()
        state = getattr(self._services, "runtime_state", None)
        operator_event(self._logger, "twitch.socket", "connection_observation", inherit_context=False,
                       source="lifecycle", reason=reason, stage="connection_lifecycle",
                       client_instance=self._diagnostic_id, current_client=current,
                       send_active=session.active if session is not None else False,
                       send_session_ref=session.diagnostic_ref if session is not None else None,
                       connection_state=state.twitch_connection_state if state is not None else "unknown",
                       socket_ref=self._socket_ref(socket_id), active_socket_ref=self._socket_ref(self._active_socket_id),
                       transport_ref=_transport_origin.get(), sdk_socket_count=len(sockets),
                       sdk_reconnect_count=sum(not task.done() for socket in sockets
                                               for task in getattr(socket, "_connection_tasks", ())),
                       event_count=count + 1)

    def _set_connection_state(self, state: TwitchConnectionState) -> None:
        if not self._owns_session():
            return
        analytics = getattr(self._services, "analytics", None)
        if analytics is not None and state in {"failed", "auth_required"}:
            runtime = getattr(self._services, "runtime_state", None)
            if runtime is None or runtime.twitch_connection_state != state:
                analytics.record("connection.errors", channel_id=self._settings.twitch_channel_user_id)
        if self._services.twitch is not None:
            self._services.twitch.set_chat_ready(self, state == "connected" and not self._closing_requested)
        runtime_state = getattr(self._services, "runtime_state", None)
        if runtime_state is not None:
            runtime_state.set_twitch_connection_state(state)
        self._connection_event("state_" + state)

    async def _drain_sdk_reconnects(self, sockets) -> None:
        tasks = {task for socket in sockets for task in getattr(socket, "_connection_tasks", ())
                 if not task.done() and task is not asyncio.current_task()}
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def begin_authorization(self) -> str:
        state = self._services.runtime_state
        if self._closing_requested or state is None or not state.status()[0] or state.twitch_connection_state not in ("auth_required", "connected"):
            raise ValueError("Twitch authorization is not currently required.")
        return self.adapter.begin_authorization()

    async def close(self, *args, **kwargs) -> None:
        async with self._close_lock:
            if self._closing_requested:
                if self._close_failure is not None:
                    raise self._close_failure
                return
            self._closing_requested = True
            self._retired = True
            self._closing_task = asyncio.current_task()
            sockets = self._registered_sockets()
            readers = {task for socket in sockets for task in (socket._listen_task, socket._keep_alive_task)
                       if task is not None and task is not asyncio.current_task()}
            self._connection_event("client_closing")
            # TwitchIO stops refresh work, saves, then clears managed tokens. Only
            # this close task may save now; queued refresh listeners must not later
            # replace the persisted cache with the cleared in-memory dictionary.
            try:
                handlers = self._ingress_tasks - {asyncio.current_task()}
                for task in handlers:
                    task.cancel()
                if handlers:
                    await asyncio.gather(*handlers, return_exceptions=True)
                # Let in-flight OAuth/refresh handlers finish before the final
                # token flush. Retired callbacks cannot subscribe or set status.
                events = self._event_tasks - {asyncio.current_task()}
                if events:
                    await asyncio.gather(*events, return_exceptions=True)
                await self._drain_sdk_reconnects(sockets)
                try:
                    if self._services.twitch is not None:
                        await self._services.twitch.unbind(self)
                finally:
                    # Includes not-yet-registered startup and handover sockets.
                    for socket in sockets:
                        await socket.close()
                    await super().close(*args, **{**kwargs, "save_tokens": self._tokens_loaded})
                    if readers:
                        await asyncio.gather(*readers, return_exceptions=True)
                if self._close_save_failed:
                    raise TwitchCleanupError("Could not persist Twitch authorization during shutdown.")
            except BaseException:
                self._close_failure = TwitchCleanupError("Twitch cleanup failed; verify private token storage and restart the application.")
                raise self._close_failure from None
            finally:
                # SDK close cancels listeners but does not drain its reconnect
                # tasks. Prevent an in-progress connect from resurrecting a client.
                await self._drain_sdk_reconnects(sockets | self._registered_sockets())
                self._connection_event("client_closed")
                self._closing_task = None

    async def event_error(self, payload: object) -> None:
        # A command/listener error is not evidence of terminal authorization or
        # socket failure. The supervisor independently checks the usable session.
        self._logger.error(
            "Twitch asynchronous handler failed",
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
        sockets = self._websockets[self.bot_id]
        if not sockets:
            socket = OwnedWebsocket(client=self, token_for=self.bot_id, http=self._http)
            await socket.connect(fail_once=True)
            sockets[socket.session_id] = socket
        await self.subscribe_websocket(payload=subscription, as_bot=True)

    async def event_ready(self) -> None:
        if self.bot_id not in self.tokens:
            self._set_connection_state("auth_required")
            self._logger.warning(
                "Authorize the configured bot account using Authorize Twitch in HeetKit",
                extra={"event_kind": "twitch.auth_required", "event_channel": self._account.channel},
            )
            return
        self.refresh_readiness()

    async def event_oauth_authorized(self, payload: UserTokenPayload) -> None:
        if not self._owns_session():
            return
        token = await self.add_token(payload["access_token"], payload["refresh_token"])
        if token.user_id == self.bot_id:
            self._tokens_loaded = True
            self._cached_tokens = {}
            if not self._owns_session():
                return  # close waits for this callback, then flushes its rotation.
            self._send_authorized = "user:write:chat" in token.scopes
            if not self._send_authorized:
                self._set_connection_state("auth_required")
                return
            await self.save_tokens()
            if not self._owns_session():
                return
            self._logger.info("Configured bot account OAuth authorization completed")
            if not (self._services.twitch is not None and self._services.twitch.chat_connected):
                self._set_connection_state("connecting")
                await self._subscribe_to_chat()
            self.refresh_readiness()
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
            self._send_authorized = "user:write:chat" in payload.scopes.selected
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
                    if validated is not None and validated.user_id == self.bot_id:
                        self._send_authorized = "user:write:chat" in validated.scopes
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
                except InvalidTokenException as error:
                    if recoverable_failure(error):
                        raise
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
        task = asyncio.current_task()
        self._ingress_tasks.add(task)
        try:
            await self._handle_message(message)
        finally:
            self._ingress_tasks.discard(task)

    async def _handle_message(self, message: ChatMessage) -> None:
        if self._closing_requested or self._retired:
            self._connection_event("closed_client_ingress")
            return
        # Ownership must be checked before the shared replay reservation. A late
        # retired reader must not poison the active client's copy of this event.
        try:
            send_session = self._services.twitch.chat_session(self) if self._services.twitch is not None else None
        except ChatSessionClosedError:
            self._connection_event("replaced_client_ingress")
            return
        if send_session is not None and not send_session.active:
            self._connection_event("inactive_session_ingress")
            return
        origin = _transport_origin.get()
        if (origin is not None and self._active_socket_id is not None
                and origin != self._socket_ref(self._active_socket_id)
                and not any(socket.connected and socket._ready.is_set()
                            and origin == self._socket_ref(socket.session_id)
                            for socket in self._registered_sockets())):
            # During reconnect_url handover both sockets belong to this client.
            # New ingress may precede connect() returning/old close completing.
            self._connection_event("superseded_socket_ingress")
            return
        # EventSub delivery is not an exactly-once command invocation. Reserve
        # the stable chat ID before any await so concurrent replays cannot send
        # another batch, even when the command has no cooldown.
        message_id = getattr(message, "id", None)
        channel = str(getattr(message.broadcaster, "id", message.broadcaster.name))
        if not self._chat_messages.reserve(self.bot_id, channel, message_id,
                                          origin=(self._diagnostic_id, _transport_origin.get(),
                                                  *(_dispatch_origin.get() or (None, None, None)))):
            return
        try:
            await process_twitch_message(
                message=message,
                services=self._services,
                dispatcher=self._dispatcher,
                logger=self._logger,
                correlation=self._chat_messages,
                send_session=send_session,
            )
        except Exception:
            self._logger.exception("Unexpected Twitch message processing failure")

    async def event_websocket_welcome(self, payload: object) -> None:
        if not self._owns_session():
            return
        snapshot = _socket_event.get()
        if snapshot is not None:
            if snapshot[0] < self._last_socket_sequence:
                return
            self._last_socket_sequence = snapshot[0]
        self._active_socket_id = getattr(payload, "id", None)
        self._connection_event("socket_welcome", socket_id=self._active_socket_id)
        self.refresh_readiness()

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
        if not self._owns_session():
            return
        runtime_state = getattr(self._services, "runtime_state", None)
        if runtime_state is not None and runtime_state.twitch_connection_state in (
            "auth_required", "failed"
        ):
            return
        snapshot = _socket_event.get()
        if snapshot is not None:
            if snapshot[0] < self._last_socket_sequence:
                return
            self._last_socket_sequence = snapshot[0]
        socket_id = snapshot[1] if snapshot is not None else getattr(getattr(payload, "socket", None), "session_id", None)
        # Failed SDK reconnect candidates also emit close, without ever receiving
        # a welcome/session ID. They do not own the current sending connection.
        if self._active_socket_id is not None and socket_id != self._active_socket_id:
            self._connection_event("unwelcomed_socket" if socket_id is None else "superseded_socket", socket_id=socket_id)
            return
        self._connection_event("active_socket_closed", socket_id=socket_id)
        self._set_connection_state("reconnecting")
        self._logger.warning(
            "Twitch chat connection closed; TwitchIO is handling recovery channel=%s",
            self._account.channel,
            extra={
                "event_kind": "twitch.disconnected",
                "event_channel": self._account.channel,
            },
        )


def recoverable_failure(error: Exception) -> bool:
    # InvalidTokenException also wraps validation/refresh 5xx and rate limits.
    if isinstance(error, HTTPException):
        return error.status in {408, 409, 425, 429} or error.status >= 500
    if isinstance(error, ClientResponseError):
        return error.status in {408, 425, 429} or error.status >= 500
    if isinstance(error, WebsocketConnectionException) and isinstance(error.__cause__, (HTTPException, ClientResponseError)):
        return recoverable_failure(error.__cause__)
    if isinstance(error, OSError) and (error.filename is not None or error.errno in {
            errno.EACCES, errno.EPERM, errno.ENOSPC, errno.EROFS, errno.EISDIR, errno.ENOENT, errno.ENOTDIR, errno.EIO}):
        return False
    return isinstance(error, (OSError, ClientError, TimeoutError, WebsocketConnectionException))


def rate_limit_delay(error: Exception | None) -> float:
    if isinstance(error, WebsocketConnectionException) and isinstance(error.__cause__, Exception):
        return rate_limit_delay(error.__cause__)
    if getattr(error, "status", None) != 429:
        return 0.0
    # HTTPException discards headers; websocket handshake errors retain them.
    delay = 120.0
    headers = getattr(error, "headers", None) or {}
    for name in ("Retry-After", "Ratelimit-Reset"):
        value = headers.get(name)
        if value is None:
            continue
        try:
            seconds = float(value) - (wall_time() if name == "Ratelimit-Reset" else 0)
        except (ValueError, TypeError):
            try:
                seconds = parsedate_to_datetime(value).timestamp() - wall_time()
            except (ValueError, TypeError, OverflowError):
                continue
        if isfinite(seconds):
            delay = max(delay, seconds)
    return delay


async def _retire_client(bot, start_task: asyncio.Task, logger) -> None:
    """Revoke ingress/sends first; prove cleanup finished before permitting reuse."""
    bot._retired = True
    twitch = getattr(getattr(bot, "_services", None), "twitch", None)
    if twitch is not None:
        twitch.set_chat_ready(bot, False)
    # Cancel startup/connect as well as start's waiter. SDK start's finally may
    # call close itself, which the client's close lock serializes with this call.
    start_task.cancel()
    closing = asyncio.create_task(bot.close(save_tokens=False))
    done, pending = await asyncio.wait({start_task, closing}, timeout=CLEANUP_DEADLINE)
    if pending:
        for task in pending:
            task.cancel()
            task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
        logger.error("Twitch cleanup deadline exceeded; replacement blocked", extra={"event_kind": "twitch.failed"})
        raise TwitchCleanupError("Twitch cleanup did not finish; restart the application before reconnecting.")
    if not start_task.cancelled():
        start_error = start_task.exception()
        if isinstance(start_error, TwitchCleanupError):
            raise start_error
    # Startup failure is classified by the caller. Cleanup failure is always
    # terminal, including persistence errors; never silently replace that client.
    if not closing.cancelled() and closing.exception() is not None:
        raise TwitchCleanupError("Twitch client shutdown failed; check private token storage and restart.") from None


async def run_twitch_bot(
    settings: Settings,
    services: ApplicationServices,
    dispatcher: CommandDispatcher,
    logger: logging.Logger,
    stop_event: asyncio.Event | None = None,
    *,
    headless: bool = False,
) -> None:
    """One desired-running session, with bounded SDK windows and serial retirement.

    Each attempt is bounded; the number of attempts is intentionally unlimited
    while intent remains running. Backoff/counters reset only after five healthy
    minutes, so flapping welcomes cannot create an aggressive retry loop.
    """
    settings.validate_twitch_configuration()
    stop = stop_event if stop_event is not None else asyncio.Event()
    runtime = getattr(services, "runtime_state", None)
    began = monotonic()
    attempt = 0
    failures = 0
    cause = "startup"

    def progress(reason, *, delay=None):
        if runtime is not None:
            runtime.set_twitch_recovery({"reason": reason, "attempt": attempt,
                "cause": cause,
                "elapsed_seconds": max(0, int(monotonic() - began)),
                "next_retry_seconds": None if delay is None else max(0, int(delay + .999))})

    def terminal(error):
        auth = isinstance(error, InvalidTokenException) or (isinstance(error, HTTPException) and error.status == 401)
        if runtime is not None:
            runtime.set_twitch_connection_state("auth_required" if auth else "failed")
        logger.error("Twitch session requires attention error_type=%s status=%s; check authorization, access, configuration and private storage",
            type(error).__name__, getattr(error, "status", None),
            extra={"event_kind": "twitch.auth_required" if auth else "twitch.failed"})
        if isinstance(error, InvalidTokenException):
            logger.error("Twitch user token validation failed status=%s invalid_type=%s", error.status, error.invalid_type)
            return TwitchConnectionError("Twitch user token validation failed.")
        return TwitchConnectionError("Twitch session failed; check authorization, access, configuration and private storage.")

    try:
        while not stop.is_set():
            attempt += 1
            progress("startup" if attempt == 1 else "fresh_session")
            if runtime is not None:
                runtime.set_twitch_connection_state("connecting" if attempt == 1 else "reconnecting")
            try:
                bot = TwitchChatBot(settings=settings, account=settings.primary_account,
                    services=services, dispatcher=dispatcher, logger=logger)
            except Exception as error:
                raise terminal(error) from None
            bot.require_verified_identity = headless
            start_task = asyncio.create_task(bot.start(with_adapter=not headless, load_tokens=True, save_tokens=True))
            stop_task = asyncio.create_task(stop.wait())
            unhealthy_since = monotonic()
            healthy_since = None
            error = None

            def sdk_failure(record):
                # Only typed lifecycle errors are actionable. An unrelated command
                # failure/library log must not disable running intent.
                if str(record.msg).startswith("Unable to resubscribe"):
                    for value in record.args if isinstance(record.args, tuple) else ():
                        if isinstance(value, HTTPException):
                            bot._lifecycle_error = value

            try:
                with twitch_lifecycle_diagnostics(sdk_failure):
                    while not stop.is_set():
                        done, _ = await asyncio.wait({start_task, stop_task}, timeout=RECOVERY_POLL,
                                                    return_when=asyncio.FIRST_COMPLETED)
                        if stop.is_set():
                            break
                        if start_task in done:
                            # A running SDK client should block until explicitly
                            # stopped. Unexpected normal completion also recovers.
                            start_task.result()
                            error = ConnectionError("Twitch session ended unexpectedly")
                            break
                        if bot._lifecycle_error is not None:
                            error = bot._lifecycle_error
                            break
                        usable = bot.refresh_readiness()
                        state = runtime.twitch_connection_state if runtime is not None else None
                        if state == "failed" or (state == "auth_required" and headless):
                            raise TwitchConnectionError("Twitch authorization/access needs attention.")
                        if state == "auth_required":
                            # Desktop intentionally keeps the local OAuth adapter
                            # alive for explicit owner authorization, without retries.
                            runtime.set_twitch_recovery(None)
                            unhealthy_since = monotonic()
                            continue
                        now = monotonic()
                        if usable:
                            unhealthy_since = now
                            if healthy_since is None:
                                healthy_since = now
                            if now - healthy_since >= STABLE_RESET:
                                failures = 0
                                attempt = 1
                                began = now
                            if runtime is not None:
                                runtime.set_twitch_recovery(None)
                        else:
                            if healthy_since is not None:
                                began = now
                                cause = "protocol_unready"
                            healthy_since = None
                            if runtime is not None:
                                runtime.set_twitch_connection_state("reconnecting" if attempt > 1 or bot._had_authorization else "connecting")
                            progress("sdk_recovery" if bot._had_authorization else "startup")
                            if now - unhealthy_since >= RECOVERY_DEADLINE:
                                error = TimeoutError("Twitch recovery stopped progressing")
                                break
            except asyncio.CancelledError:
                raise
            except Exception as failure:
                error = failure
            finally:
                stop_task.cancel()
                await asyncio.gather(stop_task, return_exceptions=True)
                await _retire_client(bot, start_task, logger)
            if stop.is_set():
                break
            if error is not None and not recoverable_failure(error):
                # Preserve actionable states set by explicit revocation/monitoring.
                if runtime is not None and runtime.twitch_connection_state in {"auth_required", "failed"}:
                    raise TwitchConnectionError("Twitch authorization/access needs attention.") from None
                raise terminal(error) from None
            failures = min(failures + 1, 6)
            delay = uniform(.5, 1.0) * min(BACKOFF_CAP, BACKOFF_BASE * 2 ** (failures - 1))
            # TwitchIO 3.3.2 discards rate-limit response headers. Conservatively
            # wait two minutes after 429 instead of immediately opening a client.
            rate_delay = rate_limit_delay(error)
            delay = max(delay, rate_delay)
            if runtime is not None:
                runtime.set_twitch_connection_state("reconnecting")
            cause = ("rate_limited" if rate_delay else
                     "service_unavailable" if isinstance(error, HTTPException) else
                     "protocol_deadline" if isinstance(error, TimeoutError) else "network_failure")
            logger.warning("Twitch recovery reason=%s attempt=%s elapsed_seconds=%s next_retry_seconds=%s",
                "deadline" if isinstance(error, TimeoutError) else "transient_failure",
                attempt, int(monotonic() - began), round(delay), extra={"event_kind": "twitch.disconnected"})
            retry_at = monotonic() + delay
            while not stop.is_set() and monotonic() < retry_at:
                progress("retry_wait", delay=retry_at - monotonic())
                try:
                    await asyncio.wait_for(stop.wait(), timeout=min(RECOVERY_POLL, retry_at - monotonic()))
                except TimeoutError:
                    pass
    except TwitchCleanupError:
        if runtime is not None:
            runtime.set_twitch_connection_state("failed")
        raise
    finally:
        if runtime is not None:
            runtime.set_twitch_recovery(None)
