"""Tests for role-to-permission mapping."""

from app.twitch.events import ChatAuthor
from app.twitch.permissions import Permission, has_permission, resolve_permission


def test_highest_twitch_role_wins() -> None:
    author = ChatAuthor(
        twitch_user_id="1",
        username="viewer",
        is_subscriber=True,
        is_vip=True,
        is_moderator=True,
    )

    assert resolve_permission(author) is Permission.MODERATOR
    assert has_permission(author, Permission.VIP)
    assert not has_permission(author, Permission.BROADCASTER)