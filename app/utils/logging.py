"""Logging setup shared by application entry points."""

import logging
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from threading import RLock


RECENT_LOG_LIMIT = 500
EVENT_CONTEXT_ATTRIBUTES = {
    "event_username": "username",
    "event_command": "command",
    "event_channel": "channel",
    "event_retry_after_seconds": "retry_after_seconds",
    "event_duration_seconds": "duration_seconds",
    "event_model": "model",
    "event_provider": "provider",
    "event_setting": "setting",
    "event_action": "action",
}
EventContextValue = str | int | float | bool


@dataclass(frozen=True, slots=True)
class RecentLogEntry:
    id: int
    timestamp: str
    level: str
    source: str
    message: str
    event_kind: str | None = None
    context: dict[str, EventContextValue] = field(default_factory=dict)


class RecentLogBuffer:
    """Thread-safe bounded history used by local presentation layers."""

    def __init__(self, max_entries: int = RECENT_LOG_LIMIT) -> None:
        if max_entries < 1:
            raise ValueError("Recent log buffer size must be positive.")
        self._entries: deque[RecentLogEntry] = deque(maxlen=max_entries)
        self._lock = RLock()
        self._next_id = 1

    def append(self, record: logging.LogRecord, message: str) -> None:
        timestamp = datetime.fromtimestamp(record.created, tz=timezone.utc)
        event_kind = getattr(record, "event_kind", None)
        if not isinstance(event_kind, str) or not event_kind.strip():
            event_kind = None
        context: dict[str, EventContextValue] = {}
        for attribute, field_name in EVENT_CONTEXT_ATTRIBUTES.items():
            value = getattr(record, attribute, None)
            if isinstance(value, (str, int, float, bool)) and not isinstance(value, bytes):
                context[field_name] = value
        with self._lock:
            self._entries.append(
                RecentLogEntry(
                    id=self._next_id,
                    timestamp=timestamp.isoformat(timespec="milliseconds").replace(
                        "+00:00", "Z"
                    ),
                    level=record.levelname,
                    source=record.name,
                    message=message,
                    event_kind=event_kind,
                    context=context,
                )
            )
            self._next_id += 1

    def recent(self, *, after_id: int = 0, limit: int = 200) -> list[dict[str, object]]:
        with self._lock:
            entries = [entry for entry in self._entries if entry.id > after_id]
            return [asdict(entry) for entry in entries[:limit]]


class RecentLogHandler(logging.Handler):
    def __init__(self, buffer: RecentLogBuffer) -> None:
        super().__init__()
        self._buffer = buffer

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
            if record.exc_info:
                formatter = self.formatter or logging.Formatter()
                message = f"{message}\n{formatter.formatException(record.exc_info)}"
            self._buffer.append(record, message)
        except Exception:
            self.handleError(record)


_recent_log_buffer = RecentLogBuffer()
_recent_log_handler = RecentLogHandler(_recent_log_buffer)


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    root_logger = logging.getLogger()
    if _recent_log_handler not in root_logger.handlers:
        root_logger.addHandler(_recent_log_handler)
    logging.getLogger("twitchio").setLevel(logging.CRITICAL + 1)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def get_recent_log_buffer() -> RecentLogBuffer:
    return _recent_log_buffer
