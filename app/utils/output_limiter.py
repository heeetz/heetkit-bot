"""Global bot output rate limiter.

Enforces a minimum interval between any two outgoing bot messages,
independent of which command produced them.
"""

from collections.abc import Callable
from time import monotonic


class OutputLimiter:
    """Allows at most one bot message every ``interval`` seconds."""

    def __init__(
        self,
        interval: float = 5.0,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if interval < 0:
            raise ValueError("Output limiter interval cannot be negative.")
        self._interval = interval
        self._clock = clock
        self._last_send: float | None = None

    def try_acquire(self) -> bool:
        """Return *True* and record a send if the interval has elapsed."""
        now = self._clock()
        if self._last_send is not None and (now - self._last_send) < self._interval:
            return False
        self._last_send = now
        return True
