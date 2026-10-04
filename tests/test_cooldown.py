"""Tests for per-user and global cooldown handling."""

import pytest

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


def test_zero_cooldowns_do_not_retain_chatters_or_commands() -> None:
    manager = CooldownManager(clock=lambda: 0.0)
    for index in range(10_000):
        assert manager.check_and_record(f"cmd-{index}", f"user-{index}", CooldownPolicy()).allowed

    assert not manager._uses
    assert not manager._commands


def test_global_only_cooldown_does_not_retain_distinct_chatters() -> None:
    now = 0.0
    manager = CooldownManager(clock=lambda: now)
    policy = CooldownPolicy(global_seconds=1.0)
    for index in range(10_000):
        now = float(index)
        assert manager.check_and_record("trigger:hello", f"user-{index}", policy).allowed

    assert len(manager._uses) == 1
    assert len(manager._commands) == 1


def test_many_distinct_chatters_across_elapsed_windows_have_bounded_history() -> None:
    now = 0.0
    manager = CooldownManager(clock=lambda: now)
    policy = CooldownPolicy(per_user_seconds=10.0)
    cohort_size = 2_000
    for window in range(20):
        now = float(window * 11)
        for index in range(cohort_size):
            assert manager.check_and_record(
                f"custom:{index % 4}", f"user-{window}-{index}", policy,
            ).allowed
            assert len(manager._uses) <= cohort_size + 1

        assert len(manager._uses) == cohort_size
        assert len(manager._commands) == 4


def test_idle_history_is_reclaimed_in_bounded_batches_on_uncapped_requests() -> None:
    now = 0.0
    manager = CooldownManager(clock=lambda: now)
    for index in range(1_000):
        assert manager.check_and_record(
            f"removed-{index}", "user", CooldownPolicy(global_seconds=10.0),
        ).allowed

    now = 10.0
    assert manager.check_and_record("uncapped", "user", CooldownPolicy()).allowed
    # A large idle cache must not cause one request to scan the entire cache.
    assert 1_000 - 64 <= len(manager._uses) < 1_000
    for _ in range(1_000):
        manager.check_and_record("uncapped", "user", CooldownPolicy())
    assert not manager._uses
    assert not manager._commands


def test_cleanup_preserves_long_active_windows_and_visits_shorter_windows() -> None:
    now = 0.0
    manager = CooldownManager(clock=lambda: now)
    long_policy = CooldownPolicy(global_seconds=100.0, per_user_seconds=200.0)
    assert manager.check_and_record("long", "first", long_policy).allowed
    for index in range(1_000):
        assert manager.check_and_record(
            "short", f"user-{index}", CooldownPolicy(per_user_seconds=1.0),
        ).allowed

    now = 2.0
    for _ in range(100):
        rejected = manager.check_and_record("long", "second", long_policy)
        assert not rejected.allowed
        assert rejected.retry_after == 98.0
    assert len(manager._uses) == 2
    assert set(manager._commands) == {"long"}

    now = 100.0
    rejected = manager.check_and_record("long", "first", long_policy)
    assert not rejected.allowed
    assert rejected.retry_after == 100.0
    assert manager.check_and_record("long", "second", long_policy).allowed
    now = 200.0
    assert manager.check_and_record("long", "first", long_policy).allowed


def test_live_per_user_override_applies_to_other_retained_chatters() -> None:
    now = 0.0
    manager = CooldownManager(clock=lambda: now)
    initial = CooldownPolicy(per_user_seconds=10.0)
    assert manager.check_and_record("cmd", "first", initial).allowed
    assert manager.check_and_record("cmd", "second", initial).allowed

    now = 5.0
    extended = CooldownPolicy(per_user_seconds=100.0)
    first = manager.check_and_record("cmd", "first", extended)
    assert not first.allowed
    assert first.retry_after == 95.0
    now = 11.0
    second = manager.check_and_record("cmd", "second", extended)
    assert not second.allowed
    assert second.retry_after == 89.0
    now = 100.0
    assert manager.check_and_record("cmd", "second", extended).allowed


@pytest.mark.parametrize("field_name", ["global_seconds", "per_user_seconds"])
def test_live_overrides_can_extend_shorten_and_disable_windows(field_name: str) -> None:
    now = 0.0
    manager = CooldownManager(clock=lambda: now)
    assert manager.check_and_record("cmd", "user", CooldownPolicy(**{field_name: 20.0})).allowed

    now = 5.0
    extended = manager.check_and_record("cmd", "user", CooldownPolicy(**{field_name: 60.0}))
    assert not extended.allowed
    assert extended.retry_after == 55.0
    now = 10.0
    assert manager.check_and_record("cmd", "user", CooldownPolicy(**{field_name: 10.0})).allowed
    assert manager.check_and_record("cmd", "user", CooldownPolicy()).allowed
    assert not manager._uses
    assert not manager._commands


def test_repeated_successes_do_not_accumulate_expiration_bookkeeping() -> None:
    now = 0.0
    manager = CooldownManager(clock=lambda: now)
    policy = CooldownPolicy(global_seconds=1.0, per_user_seconds=2.0)
    for index in range(10_000):
        now = float(index * 2)
        assert manager.check_and_record("cmd", "user", policy).allowed
        assert len(manager._uses) == 2
        assert len(manager._commands) == 1


def test_reclaimed_history_is_not_revived_by_later_overrides() -> None:
    now = 0.0
    manager = CooldownManager(clock=lambda: now)
    assert manager.check_and_record("cmd", "user", CooldownPolicy(per_user_seconds=1.0)).allowed
    now = 1.0
    assert manager.check_and_record("other", "user", CooldownPolicy()).allowed
    assert not manager._uses
    assert manager.check_and_record("cmd", "user", CooldownPolicy(per_user_seconds=100.0)).allowed
