"""Transport-neutral chat event types consumed by commands."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass


ChatResponder = Callable[[str], Awaitable[object]]


@dataclass(frozen=True, slots=True)
class ChatAuthor:
    twitch_user_id: str
    username: str
    is_subscriber: bool = False
    is_vip: bool = False
    is_moderator: bool = False
    is_broadcaster: bool = False


@dataclass(frozen=True, slots=True)
class IncomingChatMessage:
    channel: str
    content: str
    author: ChatAuthor
    respond: ChatResponder