"""Permission resolution based on Twitch chat roles."""

from enum import IntEnum

from app.twitch.events import ChatAuthor


class Permission(IntEnum):
    USER = 0
    SUBSCRIBER = 1
    VIP = 2
    MODERATOR = 3
    BROADCASTER = 4


def resolve_permission(author: ChatAuthor) -> Permission:
    if author.is_broadcaster:
        return Permission.BROADCASTER
    if author.is_moderator:
        return Permission.MODERATOR
    if author.is_vip:
        return Permission.VIP
    if author.is_subscriber:
        return Permission.SUBSCRIBER
    return Permission.USER


def has_permission(author: ChatAuthor, required: Permission) -> bool:
    return resolve_permission(author) >= required