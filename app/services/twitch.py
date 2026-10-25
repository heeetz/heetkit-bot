"""Small adapters for Twitch API calls used by command services."""

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime
from time import monotonic
from typing import Any
from twitchio import Client
from app.config.settings import Settings
from app.ai_user_blocks import verified_user_id
from app.twitch.message_correlation import ChatMessageCorrelation
from app.twitch.sending import ChatSender, ChatSendSession, ChatSessionClosedError
from app.utils.output_limiter import OutputLimiter

logger = logging.getLogger(__name__)

CATEGORY_CACHE_TTL_SECONDS = 90.0


class TwitchAPIService:
    """Expose the already-authenticated TwitchIO client to command handlers."""

    def __init__(
        self,
        *,
        category_cache_ttl: float = CATEGORY_CACHE_TTL_SECONDS,
        clock: Callable[[], float] = monotonic,
        output_limiter: OutputLimiter | None = None,
    ) -> None:
        self._client: Any | None = None
        self._channel_user_id: str | None = None
        self._token_user_id: str | None = None
        self._category_cache_ttl = category_cache_ttl
        self._clock = clock
        self._cached_category: str | None = None
        self._category_cached_at: float | None = None
        self._monitor_client: Client | None = None
        # Application-owned: preserve echo/replay protection across session binds.
        self.chat_messages = ChatMessageCorrelation()
        self.output_limiter = output_limiter if output_limiter is not None else OutputLimiter()
        self._send_session = ChatSendSession()
        self._retiring_sends: set[asyncio.Task] = set()
        self._channel_name: str | None = None
        self._chat_stopping = False
        self.human_messages = 0
        self.on_chat_session_changed: Callable[[], None] | None = None

    @property
    def chat_connected(self) -> bool:
        return self._client is not None and self._send_session.active

    def record_human_message(self, message) -> None:
        """Count accepted, current-session ingress, never our own output/echo.

        EventSub IDs are reserved by the ingress adapter before this hook. Keep
        only a counter: no message bodies or viewer identities are retained.
        """
        if (self.chat_connected and message.send_session is self._send_session
                and message.channel.casefold() == (self._channel_name or "").casefold()
                and message.author.twitch_user_id != self._token_user_id
                and not message.is_outgoing and not message.author.is_bot):
            self.human_messages += 1

    async def get_broadcaster_live(self, settings: Settings) -> bool:
        """Get Streams using TwitchIO's app authentication, even without chat.

        No user-token cache, EventSub session, OAuth listener or extra scopes.
        The caller bounds requests and handles unknown status/backoff.
        """
        settings.validate_twitch_configuration()
        if self._monitor_client is None:
            client = Client(client_id=settings.twitch_client_id,
                client_secret=settings.twitch_client_secret.get_secret_value())
            self._monitor_client = client
            try:
                await client.login(load_tokens=False, save_tokens=False)
            except BaseException:
                await self.close_stream_monitor()
                raise
        streams = self._monitor_client.fetch_streams(
            user_ids=[settings.twitch_channel_user_id], first=1, max_results=1)
        return await anext(streams, None) is not None

    async def close_stream_monitor(self) -> None:
        client, self._monitor_client = self._monitor_client, None
        if client is not None:
            await client.close(save_tokens=False)

    def bind(self, client: Any, channel_user_id: str, token_user_id: str, *, channel_name: str | None = None) -> None:
        self.suspend_chat()
        self._client = client
        self._channel_user_id = channel_user_id
        self._token_user_id = token_user_id
        self._cached_category = None
        self._category_cached_at = None
        self._channel_name = channel_name or channel_user_id
        self._chat_stopping = False

    def chat_session(self, client: Any) -> ChatSendSession:
        if client is not self._client:
            raise ChatSessionClosedError("Twitch chat session has been replaced.")
        return self._send_session

    def suspend_chat(self) -> None:
        """Invalidate captured senders synchronously, before lifecycle work yields."""
        self._send_session.invalidate()
        for task in self._send_session.tasks:
            self._retiring_sends.add(task)
            task.add_done_callback(self._retiring_sends.discard)
        if self.on_chat_session_changed is not None:
            self.on_chat_session_changed()

    def set_chat_ready(self, client: Any, ready: bool) -> None:
        if client is not self._client:
            return
        if ready and not self._chat_stopping:
            if not self._send_session.active:
                self._send_session = ChatSendSession(active=True)
                self.human_messages = 0
                if self.on_chat_session_changed is not None:
                    self.on_chat_session_changed()
        else:
            self.suspend_chat()

    def stop_chat(self) -> None:
        self._chat_stopping = True
        self.suspend_chat()

    async def unbind(self, client: Any) -> None:
        if client is not self._client:
            return
        self.stop_chat()
        self._client = self._channel_user_id = self._token_user_id = None
        self._cached_category = self._category_cached_at = None
        if self._retiring_sends:
            await asyncio.gather(*tuple(self._retiring_sends), return_exceptions=True)

    def chat_sender(self) -> ChatSender:
        """Capture a sender now; delayed callers must keep it across their awaits.

        A sender never follows a later connection/channel binding. This is the
        seam for non-command producers; it does not schedule or queue messages.
        """
        client, channel, account = self._client, self._channel_user_id, self._token_user_id
        session, channel_name = self._send_session, self._channel_name
        if client is None or not session.active:
            raise ChatSessionClosedError("Twitch chat is not connected.")

        async def send(content: str) -> object:
            async def respond(text: str) -> object:
                return await client.create_partialuser(channel).send_message(
                    message=text, sender=account, token_for=account,
                )

            return await self.chat_messages.send(account, channel, respond, content)

        return ChatSender(send, logger, self.output_limiter, session,
                          context={"source": "announcement", "channel": channel_name})

    async def begin_authorization(self) -> str:
        """Issue state on the backend loop for the currently bound bot session."""
        if self._client is None:
            raise ValueError("Twitch authorization is not ready. Try again after starting the bot.")
        return self._client.begin_authorization()

    async def get_current_category(self) -> str | None:
        """Return the live channel category, caching successful and empty lookups."""
        now = self._clock()
        if (
            self._category_cached_at is not None
            and now - self._category_cached_at < self._category_cache_ttl
        ):
            return self._cached_category

        category: str | None = None
        if self._client is not None and self._channel_user_id is not None:
            try:
                streams = self._client.fetch_streams(
                    user_ids=[self._channel_user_id],
                    token_for=self._token_user_id,
                    first=1,
                    max_results=1,
                )
                stream = await anext(streams, None)
                raw_category = getattr(stream, "game_name", None) if stream is not None else None
                if isinstance(raw_category, str) and raw_category.strip():
                    category = raw_category.strip()
            except Exception as error:
                logger.warning(
                    "Could not refresh Twitch stream category: %s",
                    type(error).__name__,
                )

        self._cached_category = category
        self._category_cached_at = now
        return category

    async def get_followed_at(self, user_id: str) -> datetime | None:
        if self._client is None or self._channel_user_id is None or self._token_user_id is None:
            return None

        channel_users = await self._client.fetch_users(
            ids=[self._channel_user_id],
            token_for=self._token_user_id,
        )
        if not channel_users:
            return None

        followers = await channel_users[0].fetch_followers(
            user=user_id,
            first=1,
            max_results=1,
            token_for=self._token_user_id,
        )
        follower = await anext(followers.followers, None)
        return None if follower is None else follower.followed_at

    async def resolve_user_id(self, username: str) -> str | None:
        """Resolve an offline-capable login through the existing authenticated client."""
        if self._client is None:
            return None
        try:
            users = await self._client.fetch_users(logins=[username], token_for=self._token_user_id)
            user = next((user for user in users if getattr(user, "name", "").lower() == username), None)
            return verified_user_id(getattr(user, "id", None))
        except Exception as error:
            logger.warning("Could not resolve Twitch login for AI block error_type=%s", type(error).__name__)
            return None
