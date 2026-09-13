"""Application runtime information."""

from collections.abc import Callable
from time import monotonic


class RuntimeService:
    """Reports elapsed time since the current application instance was created."""

    def __init__(self, clock: Callable[[], float] = monotonic) -> None:
        self._clock = clock
        self._started_at = clock()

    def elapsed_seconds(self) -> int:
        return max(0, int(self._clock() - self._started_at))