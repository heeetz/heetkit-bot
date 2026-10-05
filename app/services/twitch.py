"""Small adapters for Twitch API calls used by command services."""

import logging
from collections.abc import Callable
from datetime import datetime
from time import monotonic
from typing import Any

logger = logging.getLogger(__name__)

CATEGORY_CACHE_TTL_SECONDS = 90.0


class TwitchAPIService:
    """Expose the already-authenticated TwitchIO client to command handlers."""

    def __init__(
        self,
        *,
        category_cache_ttl: float = CATEGORY_CACHE_TTL_SECONDS,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._client: Any | None = None
        self._channel_user_id: str | None = None
        self._token_user_id: str | None = None
        self._category_cache_ttl = category_cache_ttl
        self._clock = clock
        self._cached_category: str | None = None
        self._category_cached_at: float | None = None

    def bind(self, client: Any, channel_user_id: str, token_user_id: str) -> None:
        self._client = client
        self._channel_user_id = channel_user_id
        self._token_user_id = token_user_id
        self._cached_category = None
        self._category_cached_at = None

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
