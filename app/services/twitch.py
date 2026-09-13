"""Small adapters for Twitch API calls used by command services."""

from datetime import datetime
from typing import Any


class TwitchAPIService:
    """Expose the already-authenticated TwitchIO client to command handlers."""

    def __init__(self) -> None:
        self._client: Any | None = None
        self._channel_user_id: str | None = None
        self._token_user_id: str | None = None

    def bind(self, client: Any, channel_user_id: str, token_user_id: str) -> None:
        self._client = client
        self._channel_user_id = channel_user_id
        self._token_user_id = token_user_id

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
