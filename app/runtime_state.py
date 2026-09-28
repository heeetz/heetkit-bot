"""Thread-safe runtime controls shared by the bot and local control panel."""

from threading import RLock
from time import monotonic
from collections.abc import Iterable

from app.config.personalities import AI_PERSONALITY_PRESETS
from config import AI_MEMORY_ENABLED, ACTIVE_AI_PERSONALITY


class RuntimeState:
    def __init__(self) -> None:
        self._lock = RLock()
        self._command_enabled: dict[str, bool] = {}
        self._ai_enabled = True
        self._ai_memory_enabled = AI_MEMORY_ENABLED
        self._active_ai_personality = ACTIVE_AI_PERSONALITY
        self._bot_running = False
        self._started_at: float | None = None
        self._uptime_started_at = monotonic()

    @property
    def available_personalities(self) -> tuple[str, ...]:
        return tuple(AI_PERSONALITY_PRESETS)

    @property
    def runtime_toggleable_commands(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._command_enabled)

    def configure_commands(self, command_names: Iterable[str]) -> None:
        with self._lock:
            self._command_enabled = {
                name: self._command_enabled.get(name, True)
                for name in command_names
            }

    def is_command_enabled(self, command_name: str) -> bool:
        with self._lock:
            if command_name == "ask" and not self._ai_enabled:
                return False
            return self._command_enabled.get(command_name, True)

    def set_command_enabled(self, command_name: str, enabled: bool) -> None:
        with self._lock:
            if command_name in self._command_enabled:
                self._command_enabled[command_name] = enabled

    def command_enabled(self, command_name: str) -> bool:
        with self._lock:
            return self._command_enabled.get(command_name, True)

    @property
    def ai_enabled(self) -> bool:
        with self._lock:
            return self._ai_enabled

    def set_ai_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._ai_enabled = enabled

    @property
    def ai_memory_enabled(self) -> bool:
        with self._lock:
            return self._ai_memory_enabled

    def set_ai_memory_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._ai_memory_enabled = enabled

    @property
    def active_ai_personality(self) -> str:
        with self._lock:
            return self._active_ai_personality

    def set_active_ai_personality(self, personality: str) -> None:
        if personality not in AI_PERSONALITY_PRESETS:
            raise ValueError(f"Unknown AI personality: {personality}")
        with self._lock:
            self._active_ai_personality = personality

    def set_bot_running(self, running: bool) -> None:
        with self._lock:
            self._bot_running = running
            self._started_at = monotonic() if running else None

    def elapsed_seconds(self) -> int:
        with self._lock:
            return max(0, int(monotonic() - self._uptime_started_at))

    def status(self) -> tuple[bool, int]:
        with self._lock:
            if not self._bot_running or self._started_at is None:
                return False, 0
            return True, max(0, int(monotonic() - self._started_at))
