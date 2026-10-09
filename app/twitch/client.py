"""TwitchIO adapter that delegates chat behavior to application services."""

import asyncio
import logging
import os
import secrets
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
from app.utils.text import parse_command


class TwitchConnectionError(RuntimeError):
    """A Twitch connection failure that is safe to expose at the application boundary."""


OAUTH_REDIRECT_URI = "http://localhost:4343/oauth/callback"
CHAT_SCOPES = Scopes(["user:read:chat", "user:write:chat", "user:bot", "moderator:read:followers"])
OAUTH_STATE_TTL_SECONDS = 300.0


class DesktopOAuthAdapter(AiohttpAdapter):
    """Bind TwitchIO's existing code exchange to one explicit desktop attempt."""

    def __init__(self, *, clock: Callable[[], float] = monotonic, **kwargs) -> None:
        self._clock = clock
        self._pending_state: tuple[str, float] | None = None
        super().__init__(**kwargs)

    def begin_authorization(self) -> str:
        state = secrets.token_urlsafe(32)
        payload = self.client.http.get_authorization_url(
            scopes=CHAT_SCOPES,
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


def to_incoming_chat_message(message: ChatMessage) -> IncomingChatMessage:
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
        ),
        respond=message.respond,
    )


async def process_twitch_message(
    message: ChatMessage,
    services: ApplicationServices,
    dispatcher: CommandDispatcher,
    logger: logging.Logger,
) -> None:
    """Persist the chatter and route a mapped Twitch event to the dispatcher."""

    try:
        incoming = to_incoming_chat_message(message)
    except (AttributeError, TypeError):
        logger.exception("Could not map incoming Twitch chat message")
        return

    # Check if message should be filtered out
    if not services.filter_manager.filter_message(incoming.content):
        logger.info(
            "Filtered out message user=%s channel=%s",
            incoming.author.username,
            incoming.channel,
            extra={
                "event_kind": "chat.filtered",
                "event_username": incoming.author.username,
                "event_channel": incoming.channel,
            },
        )
        return

    # Decide before recording request content; ignored AI input must stay out of
    # chat logs and memory just like input rejected by profile filters.
    prefix = getattr(getattr(services, "settings", None), "command_prefix", "!")
    parsed = parse_command(incoming.content, prefix)
    policy = getattr(services, "ai_request_policy", None)
    if parsed is not None and parsed[0] == "ask" and policy is not None:
        if policy.check(parsed[1]) == PolicyDecision.IGNORE:
            logger.info("AI request ignored by safety policy")
            return

    logger.info(
        "Incoming chat message channel=%s author=%s content=%r",
        incoming.channel,
        incoming.author.username,
        incoming.content,
        extra={
            "event_kind": "chat.incoming",
            "event_channel": incoming.channel,
            "event_username": incoming.author.username,
        },
    )
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
        super().__init__(
            client_id=settings.twitch_client_id,
            client_secret=settings.twitch_client_secret.get_secret_value(),
            bot_id=account.user_id,
            prefix=settings.command_prefix,
            redirect_uri=OAUTH_REDIRECT_URI,
            scopes=CHAT_SCOPES,
            adapter=DesktopOAuthAdapter(host="localhost", port=4343),
        )
        if services.twitch is not None:
            services.twitch.bind(self, account.channel_user_id, account.user_id)

    def _set_connection_state(self, state: TwitchConnectionState) -> None:
        runtime_state = getattr(self._services, "runtime_state", None)
        if runtime_state is not None:
            runtime_state.set_twitch_connection_state(state)

    def begin_authorization(self) -> str:
        state = self._services.runtime_state
        if self._closing_requested or state is None or not state.status()[0] or state.twitch_connection_state != "auth_required":
            raise ValueError("Twitch authorization is not currently required.")
        return self.adapter.begin_authorization()

    async def close(self, *args, **kwargs) -> None:
        self._closing_requested = True
        await super().close(*args, **kwargs)

    async def setup_hook(self) -> None:
        if self.bot_id not in self.tokens:
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
            await self.save_tokens()
            self._logger.info("Configured bot account OAuth authorization completed")
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
        await super().load_tokens(str(self._token_file))

    async def save_tokens(self, path: str | None = None, /) -> None:
        self._token_file.parent.mkdir(parents=True, exist_ok=True)
        await super().save_tokens(str(self._token_file))
        try:
            os.chmod(self._token_file, 0o600)
        except OSError:
            self._logger.warning("Could not restrict local Twitch token file permissions")

    async def event_message(self, message: ChatMessage) -> None:
        try:
            await process_twitch_message(
                message=message,
                services=self._services,
                dispatcher=self._dispatcher,
                logger=self._logger,
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
        if socket_id is not None and socket_id != self._active_socket_id:
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
    stop_task: asyncio.Task[None] | None = None

    def terminal_failure(state: TwitchConnectionState, message: str) -> None:
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

    try:
        if stop_event is not None:
            stop_task = asyncio.create_task(close_when_requested())
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
