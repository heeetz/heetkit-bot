"""Tests for per-user and global cooldown handling."""

import pytest

from app.utils.cooldown import CooldownManager, CooldownPolicy


@pytest.mark.parametrize("policy,timeline", [
    pytest.param(CooldownPolicy(global_seconds=30), [
        (0, "alice", 0), (0, "bob", 30), (29, "bob", 1), (30, "bob", 0),
    ], id="global"),
    pytest.param(CooldownPolicy(per_user_seconds=20), [
        (0, "alice", 0), (5, "bob", 0), (10, "alice", 10),
        (20, "alice", 0), (21, "bob", 4), (25, "bob", 0),
    ], id="per-user"),
    pytest.param(CooldownPolicy(global_seconds=10, per_user_seconds=30), [
        (0, "alice", 0), (5, "bob", 5), (11, "bob", 0), (15, "alice", 15),
        (22, "charlie", 0), (33, "alice", 0),
    ], id="combined"),
])
def test_cooldown_timeline(policy, timeline):
    now = 0
    manager = CooldownManager(clock=lambda: now)
    for now, user, remaining in timeline:
        decision = manager.check_and_record("command", user, policy)
        assert (decision.allowed, decision.retry_after) == (remaining == 0, remaining), (now, user)


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
