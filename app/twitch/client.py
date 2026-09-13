"""TwitchIO adapter that delegates chat behavior to application services."""

import asyncio
import logging
import os
from pathlib import Path

from twitchio import ChatMessage, Scopes, eventsub
from twitchio.authentication import UserTokenPayload
from twitchio.exceptions import HTTPException, InvalidTokenException
from twitchio.ext import commands
from twitchio.payloads import TokenRefreshedPayload
from twitchio.web import AiohttpAdapter
from sqlalchemy.exc import SQLAlchemyError

from app.commands.registry import CommandDispatcher
from app.config.settings import Settings, TwitchAccountSettings
from app.services.facade import ApplicationServices
from app.twitch.events import ChatAuthor, IncomingChatMessage


class TwitchConnectionError(RuntimeError):
    """A Twitch connection failure that is safe to expose at the application boundary."""


OAUTH_REDIRECT_URI = "http://localhost:4343/oauth/callback"
CHAT_SCOPES = Scopes(["user:read:chat", "user:write:chat", "user:bot"])


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
        )
        return

    logger.info(
        "Incoming chat message channel=%s author=%s content=%r",
        incoming.channel,
        incoming.author.username,
        incoming.content,
    )
    try:
        await services.users.record_seen(incoming.author)
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
        self._account = account
        self._services = services
        self._dispatcher = dispatcher
        self._logger = logger
        self._token_file = Path(settings.twitch_token_file)
        super().__init__(
            client_id=settings.twitch_client_id,
            client_secret=settings.twitch_client_secret.get_secret_value(),
            bot_id=account.user_id,
            prefix=settings.command_prefix,
            redirect_uri=OAUTH_REDIRECT_URI,
            scopes=CHAT_SCOPES,
            adapter=AiohttpAdapter(host="localhost", port=4343),
        )

    async def setup_hook(self) -> None:
        if self.bot_id not in self.tokens:
            self._logger.info("Waiting for Twitch bot OAuth authorization")
            return
        await self._subscribe_to_chat()

    async def _subscribe_to_chat(self) -> None:
        self._logger.info("Subscribing to Twitch chat channel=%s", self._account.channel)
        subscription = eventsub.ChatMessageSubscription(
            broadcaster_user_id=self._account.channel_user_id,
            user_id=self._account.user_id,
        )
        await self.subscribe_websocket(payload=subscription, as_bot=True)

    async def event_ready(self) -> None:
        if self.bot_id not in self.tokens:
            self._logger.warning(
                "Authorize the configured bot account at "
                "http://localhost:4343/oauth?scopes=user%3Aread%3Achat%20user%3Awrite%3Achat%20user%3Abot&force_verify=true"
            )
            return
        self._logger.info(
            "Twitch connection ready account=%s channel=%s",
            self._account.username,
            self._account.channel,
        )

    async def event_oauth_authorized(self, payload: UserTokenPayload) -> None:
        token = await self.add_token(payload["access_token"], payload["refresh_token"])
        if token.user_id == self.bot_id:
            await self.save_tokens()
            self._logger.info("Configured bot account OAuth authorization completed")
            await self._subscribe_to_chat()
            return

        if token.user_id == self._account.channel_user_id:
            await self.remove_token(token.user_id)
            self._logger.info("Configured channel OAuth authorization completed")
            return

        await self.remove_token(token.user_id)
        self._logger.error("OAuth authorization was for an unknown account")

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

    async def event_websocket_closed(self, payload: object) -> None:
        self._logger.warning("Twitch EventSub WebSocket closed payload=%s", payload)


async def run_twitch_bot(
    settings: Settings,
    services: ApplicationServices,
    dispatcher: CommandDispatcher,
    logger: logging.Logger,
    stop_event: asyncio.Event | None = None,
) -> None:
    account = settings.primary_account
    bot = TwitchChatBot(
        settings=settings,
        account=account,
        services=services,
        dispatcher=dispatcher,
        logger=logger,
    )
    stop_task: asyncio.Task[None] | None = None

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
        logger.info("Twitch client shutdown requested")
        raise
    except InvalidTokenException as error:
        logger.error(
            "Twitch user token validation failed status=%s invalid_type=%s",
            error.status,
            error.invalid_type,
        )
        raise TwitchConnectionError("Twitch user token validation failed.") from None
    except HTTPException as error:
        logger.error(
            "Twitch API request failed status=%s error_type=%s",
            error.status,
            type(error).__name__,
        )
        raise TwitchConnectionError("Twitch API request failed.") from None
    except OSError as error:
        logger.error("Twitch network connection failed error_type=%s", type(error).__name__)
        raise TwitchConnectionError("Twitch network connection failed.") from None
    except Exception as error:
        logger.error("Unexpected Twitch client failure error_type=%s", type(error).__name__)
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
