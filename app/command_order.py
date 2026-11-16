"""Profile creation order shared by custom commands and chat reactions."""

from threading import Lock


def parse_creation_order(value: object) -> int:
    # The browser represents these integers exactly.
    if type(value) is not int or not 0 <= value < 2**53:
        raise ValueError("Invalid command creation order.")
    return value


class CommandCreationOrder:
    def __init__(self) -> None:
        self._last = 0
        self._lock = Lock()

    def observe(self, value: int) -> None:
        with self._lock:
            self._last = max(self._last, value)

    def next(self) -> int:
        with self._lock:
            self._last = parse_creation_order(self._last + 1)
            return self._last
