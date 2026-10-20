"""Private local heartbeat for container diagnostics; no listener or profile state."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path


DEFAULT_HEALTH_FILE = Path("/tmp/heetkit-health.json")


class HealthFile:
    def __init__(self, path: Path | None) -> None:
        self.path = path
        self._next_update = 0.0
        self._state: str | None = None

    def update(self, state: str) -> None:
        if self.path is None:
            return
        now = time.monotonic()
        if state == self._state and now < self._next_update:
            return
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent, delete=False) as output:
                temporary = Path(output.name)
                json.dump({"pid": os.getpid(), "state": state, "updated": time.monotonic()}, output)
            temporary.replace(self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        self._state = state
        self._next_update = now + 5.0

    def clear(self) -> None:
        if self.path is not None:
            self.path.unlink(missing_ok=True)


def healthy(path: Path = DEFAULT_HEALTH_FILE) -> bool:
    try:
        with path.open("rb") as source:
            payload = json.loads(source.read(1025))
        pid, updated = payload["pid"], payload["updated"]
        if type(pid) is not int or pid <= 0 or type(updated) not in (int, float):
            return False
        if payload["state"] not in {"connected", "idle"} or not 0 <= time.monotonic() - updated <= 15:
            return False
        if os.name == "posix":
            os.kill(pid, 0)
        return True
    except (OSError, ValueError, TypeError, KeyError, OverflowError):
        return False


if __name__ == "__main__":
    raise SystemExit(0 if healthy(Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_HEALTH_FILE) else 1)
