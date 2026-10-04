"""In-memory command cooldown tracking."""

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic


@dataclass(frozen=True, slots=True)
class CooldownPolicy:
    per_user_seconds: float = 0.0
    global_seconds: float = 0.0

    def __post_init__(self) -> None:
        if self.per_user_seconds < 0 or self.global_seconds < 0:
            raise ValueError("Cooldown durations cannot be negative.")


@dataclass(frozen=True, slots=True)
class CooldownResult:
    allowed: bool
    retry_after: float = 0.0


@dataclass(slots=True)
class _CommandCooldown:
    policy: CooldownPolicy
    entry_count: int = 0


class CooldownManager:
    """Tracks active cooldowns, lazily expiring history with bounded work.

    The latest effective policy applies to retained uses of that command. Once
    expired history is reclaimed, a later override cannot revive it.
    """

    _CLEANUP_BUDGET = 64

    def __init__(self, clock: Callable[[], float] = monotonic) -> None:
        self._clock = clock
        # None identifies a global window; user IDs identify per-user windows.
        self._uses: OrderedDict[tuple[str, str | None], float] = OrderedDict()
        self._commands: dict[str, _CommandCooldown] = {}

    def check_and_record(
        self,
        command_name: str,
        user_id: str,
        policy: CooldownPolicy,
    ) -> CooldownResult:
        now = self._clock()
        command = self._commands.get(command_name)
        if command is not None:
            command.policy = policy
        self._expire(now)
        global_key = (command_name, None)
        user_key = (command_name, user_id)
        remaining = max(
            self._remaining(now, self._uses.get(global_key), policy.global_seconds),
            self._remaining(
                now,
                self._uses.get(user_key),
                policy.per_user_seconds,
            ),
        )
        if remaining > 0:
            return CooldownResult(allowed=False, retry_after=remaining)

        if policy.global_seconds > 0:
            self._record(global_key, now, policy)
        if policy.per_user_seconds > 0:
            self._record(user_key, now, policy)
        return CooldownResult(allowed=True)

    def _record(
        self, key: tuple[str, str | None], now: float, policy: CooldownPolicy,
    ) -> None:
        command_name = key[0]
        command = self._commands.get(command_name)
        if command is None:
            command = self._commands[command_name] = _CommandCooldown(policy)
        if key not in self._uses:
            command.entry_count += 1
        self._uses[key] = now

    def _expire(self, now: float) -> None:
        # Rotate surviving entries so every key is visited, even when a long
        # cooldown precedes expired short windows. Each use has exactly one key;
        # refreshes never accumulate stale expiration records.
        for _ in range(min(self._CLEANUP_BUDGET, len(self._uses))):
            key, last_use = self._uses.popitem(last=False)
            command = self._commands[key[0]]
            duration = (
                command.policy.global_seconds if key[1] is None
                else command.policy.per_user_seconds
            )
            if self._remaining(now, last_use, duration) > 0:
                self._uses[key] = last_use
            else:
                command.entry_count -= 1
                if command.entry_count == 0:
                    del self._commands[key[0]]

    @staticmethod
    def _remaining(now: float, last_use: float | None, duration: float) -> float:
        if last_use is None or duration == 0:
            return 0.0
        return max(0.0, duration - (now - last_use))
