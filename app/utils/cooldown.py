"""In-memory command cooldown tracking."""

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


class CooldownManager:
    """Tracks per-command global and per-user cooldown windows."""

    def __init__(self, clock: Callable[[], float] = monotonic) -> None:
        self._clock = clock
        self._global_uses: dict[str, float] = {}
        self._user_uses: dict[tuple[str, str], float] = {}

    def check_and_record(
        self,
        command_name: str,
        user_id: str,
        policy: CooldownPolicy,
    ) -> CooldownResult:
        now = self._clock()
        remaining = max(
            self._remaining(now, self._global_uses.get(command_name), policy.global_seconds),
            self._remaining(
                now,
                self._user_uses.get((command_name, user_id)),
                policy.per_user_seconds,
            ),
        )
        if remaining > 0:
            return CooldownResult(allowed=False, retry_after=remaining)

        self._global_uses[command_name] = now
        self._user_uses[(command_name, user_id)] = now
        return CooldownResult(allowed=True)

    @staticmethod
    def _remaining(now: float, last_use: float | None, duration: float) -> float:
        if last_use is None or duration == 0:
            return 0.0
        return max(0.0, duration - (now - last_use))
