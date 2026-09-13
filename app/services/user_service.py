"""User-facing business operations backed by a repository."""

from app.database.models import User
from app.database.repository import UserRepository
from app.twitch.events import ChatAuthor


class UserService:
    def __init__(self, users: UserRepository) -> None:
        self._users = users

    async def record_seen(self, author: ChatAuthor) -> User:
        return await self._users.upsert_seen(
            twitch_user_id=author.twitch_user_id,
            username=author.username,
        )

    async def get_user(self, twitch_user_id: str) -> User | None:
        return await self._users.get_by_twitch_user_id(twitch_user_id)

    async def get_user_by_username(self, username: str) -> User | None:
        return await self._users.get_by_username(username)
