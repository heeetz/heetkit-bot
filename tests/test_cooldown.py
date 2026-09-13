"""Tests for per-user and global cooldown handling."""

from app.utils.cooldown import CooldownManager, CooldownPolicy


def test_cooldowns_apply_global_and_per_user_limits() -> None:
    now = 100.0
    manager = CooldownManager(clock=lambda: now)
    policy = CooldownPolicy(per_user_seconds=10.0, global_seconds=5.0)

    assert manager.check_and_record("ping", "first", policy).allowed
    assert not manager.check_and_record("ping", "second", policy).allowed

    now = 106.0
    second_user = manager.check_and_record("ping", "second", policy)
    first_user = manager.check_and_record("ping", "first", policy)

    assert second_user.allowed
    assert not first_user.allowed
    assert first_user.retry_after == 5.0


def test_global_cooldown_timeline_0_0_10_29_31() -> None:
    """Test global cooldown with policy global_seconds=30.0 at timeline 0, 0, 10, 29, 31s."""
    now = 0.0
    manager = CooldownManager(clock=lambda: now)
    policy = CooldownPolicy(global_seconds=30.0)

    # User A at t=0s
    res_a = manager.check_and_record("weather", "user_a", policy)
    assert res_a.allowed is True
    assert res_a.retry_after == 0.0

    # User B at t=0s
    res_b = manager.check_and_record("weather", "user_b", policy)
    assert res_b.allowed is False
    assert res_b.retry_after == 30.0

    # User C at t=10s
    now = 10.0
    res_c = manager.check_and_record("weather", "user_c", policy)
    assert res_c.allowed is False
    assert res_c.retry_after == 20.0

    # User D at t=29s
    now = 29.0
    res_d = manager.check_and_record("weather", "user_d", policy)
    assert res_d.allowed is False
    assert res_d.retry_after == 1.0

    # User E at t=31s
    now = 31.0
    res_e = manager.check_and_record("weather", "user_e", policy)
    assert res_e.allowed is True
    assert res_e.retry_after == 0.0


def test_per_user_cooldown_enforced_independently() -> None:
    """Test that per-user cooldown enforces limits per user independently."""
    now = 0.0
    manager = CooldownManager(clock=lambda: now)
    policy = CooldownPolicy(per_user_seconds=20.0)

    # User A at t=0s -> allowed
    assert manager.check_and_record("cmd", "user_a", policy).allowed is True

    # User B at t=5s -> allowed independently of user A
    now = 5.0
    assert manager.check_and_record("cmd", "user_b", policy).allowed is True

    # User A at t=10s -> blocked (10s remaining)
    now = 10.0
    res_a = manager.check_and_record("cmd", "user_a", policy)
    assert res_a.allowed is False
    assert res_a.retry_after == 10.0

    # User B at t=15s -> blocked (10s remaining)
    now = 15.0
    res_b = manager.check_and_record("cmd", "user_b", policy)
    assert res_b.allowed is False
    assert res_b.retry_after == 10.0

    # User A at t=21s -> allowed (21s > 20s)
    now = 21.0
    assert manager.check_and_record("cmd", "user_a", policy).allowed is True

    # User B still blocked at t=21s (4s remaining since t=5s)
    res_b2 = manager.check_and_record("cmd", "user_b", policy)
    assert res_b2.allowed is False
    assert res_b2.retry_after == 4.0

    # User B at t=26s -> allowed (26s - 5s > 20s)
    now = 26.0
    assert manager.check_and_record("cmd", "user_b", policy).allowed is True


def test_combined_global_and_per_user_cooldown() -> None:
    """Test combined cooldown with global_seconds=10.0 and per_user_seconds=30.0."""
    now = 0.0
    manager = CooldownManager(clock=lambda: now)
    policy = CooldownPolicy(global_seconds=10.0, per_user_seconds=30.0)

    # User A at t=0s -> allowed
    assert manager.check_and_record("cmd", "user_a", policy).allowed is True

    # User B at t=5s -> blocked by global cooldown (5s left)
    now = 5.0
    res_b = manager.check_and_record("cmd", "user_b", policy)
    assert res_b.allowed is False
    assert res_b.retry_after == 5.0

    # User B at t=11s -> allowed (global expired, user B never ran it)
    now = 11.0
    assert manager.check_and_record("cmd", "user_b", policy).allowed is True

    # User A at t=15s -> blocked by per-user cooldown (15s left)
    now = 15.0
    res_a = manager.check_and_record("cmd", "user_a", policy)
    assert res_a.allowed is False
    assert res_a.retry_after == 15.0

    # User C at t=22s -> allowed (>10s since B at 11s, C has no user cooldown)
    now = 22.0
    assert manager.check_and_record("cmd", "user_c", policy).allowed is True

    # User A at t=33s -> allowed (>30s since A at 0s, and >10s since C at 22s)
    now = 33.0
    assert manager.check_and_record("cmd", "user_a", policy).allowed is True