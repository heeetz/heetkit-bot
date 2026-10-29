"""Logging setup shared by application entry points."""

import logging
import json
import re
from collections import deque
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from threading import RLock
from uuid import uuid4


RECENT_LOG_LIMIT = 500
RECENT_LOG_BYTES = 1024 * 1024
RECENT_LOG_ENTRY_BYTES = 16 * 1024
EVENT_CONTEXT_ATTRIBUTES = {
    "event_username": "username",
    "event_command": "command",
    "event_channel": "channel",
    "event_retry_after_seconds": "retry_after_seconds",
    "event_duration_seconds": "duration_seconds",
    "event_remaining_seconds": "remaining_seconds",
    "event_drop_count": "drop_count",
    "event_pending_count": "pending_count",
    "event_model": "model",
    "event_provider": "provider",
    "event_setting": "setting",
    "event_action": "action",
    **{f"event_{name}": name for name in (
        "request_id", "event_id", "response_id", "input_message_id", "message_id",
        "command_id", "invoked_name", "source", "outcome", "reason",
        "requested_provider", "requested_model", "attempt", "fallback",
        "input_tokens", "output_tokens", "total_tokens", "error_type", "stage",
        "client_instance", "current_client", "send_active", "send_session_ref", "connection_state", "socket_ref",
        "active_socket_ref", "transport_ref", "sdk_socket_count", "sdk_reconnect_count", "event_count",
        "duplicate_origin", "duplicate_delivery", "duplicate_age_seconds",
    )},
}
EventContextValue = str | int | float | bool

_suppress_private_chat_logs: ContextVar[bool | Callable[[], bool]] = ContextVar("suppress_private_chat_logs", default=False)
_operator_context: ContextVar[dict] = ContextVar("operator_context", default={})


@contextmanager
def operator_event_scope(**context):
    """Carry bounded correlation metadata through awaited work and Burst children."""
    current = _operator_context.get()
    token = _operator_context.set({"request_id": uuid4().hex, **current, **context})
    try:
        yield
    finally:
        _operator_context.reset(token)


def event_metadata(kind: str, *, inherit_context: bool = True, **context) -> dict:
    values = {**(_operator_context.get() if inherit_context else {}), **context, "event_id": uuid4().hex}
    return {"event_kind": kind, **{
        f"event_{key}": _bounded_text(value, 512) if isinstance(value, str) else value
        for key, value in values.items()
        if f"event_{key}" in EVENT_CONTEXT_ATTRIBUTES and isinstance(value, (str, int, float, bool))
    }}


def operator_event(logger: logging.Logger, kind: str, outcome: str, *, text: str | None = None, **context) -> None:
    # Text is an explicit panel-only field at the permitted input/send boundaries.
    # Stream handlers render the fixed message, never this field or provider payloads.
    extra = event_metadata(kind, outcome=outcome, **context)
    if kind in {"command.input", "chat.outgoing"} and text is not None:
        extra["event_text"] = text
    logger.info("%s outcome=%s", kind, outcome,
                extra=extra)


def send_outcome(result: object) -> str:
    if getattr(result, "sent", None) is False:
        return "failed_send"
    if getattr(result, "sent", None) is True:
        return "confirmed_send"
    return "uncertain_send"


def _bounded_text(value: str, limit: int) -> str:
    return value[:limit].encode("utf-8", errors="replace")[:limit].decode("utf-8", errors="ignore")


@contextmanager
def privacy_log_scope(suppressed: bool | Callable[[], bool]):
    """Suppress this request's diagnostics without affecting concurrent viewers."""
    token = _suppress_private_chat_logs.set(suppressed)
    try:
        yield
    finally:
        _suppress_private_chat_logs.reset(token)


def _private_logs_suppressed() -> bool:
    value = _suppress_private_chat_logs.get()
    return value() if callable(value) else value


class PrivacyLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not _private_logs_suppressed()


@dataclass(frozen=True, slots=True)
class RecentLogEntry:
    id: int
    timestamp: str
    level: str
    source: str
    message: str
    event_kind: str | None = None
    context: dict[str, EventContextValue] = field(default_factory=dict)
    text: str | None = None
    text_truncated: bool = False


class RecentLogBuffer:
    """Thread-safe bounded history used by local presentation layers."""

    def __init__(self, max_entries: int = RECENT_LOG_LIMIT, *, max_bytes: int = RECENT_LOG_BYTES,
                 max_entry_bytes: int = RECENT_LOG_ENTRY_BYTES) -> None:
        if min(max_entries, max_bytes, max_entry_bytes) < 1:
            raise ValueError("Recent log buffer size must be positive.")
        self._entries: deque[tuple[RecentLogEntry, int]] = deque()
        self._max_entries = max_entries
        self._max_bytes = max_bytes
        self._max_entry_bytes = min(max_entry_bytes, max_bytes)
        self._bytes = 0
        self._lock = RLock()
        self._next_id = 1

    def append(self, record: logging.LogRecord, message: str) -> None:
        timestamp = datetime.fromtimestamp(record.created, tz=timezone.utc)
        event_kind = getattr(record, "event_kind", None)
        if not isinstance(event_kind, str) or not event_kind.strip():
            event_kind = None
        elif event_kind:
            event_kind = _bounded_text(event_kind, 128)
        context: dict[str, EventContextValue] = {}
        for attribute, field_name in EVENT_CONTEXT_ATTRIBUTES.items():
            value = getattr(record, attribute, None)
            if isinstance(value, (str, int, float, bool)) and not isinstance(value, bytes):
                context[field_name] = _bounded_text(value, 512) if isinstance(value, str) else value
        text = getattr(record, "event_text", None) if event_kind in {"command.input", "chat.outgoing"} else None
        text = text if isinstance(text, str) else None
        with self._lock:
            entry = RecentLogEntry(
                id=self._next_id,
                timestamp=timestamp.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                level=_bounded_text(record.levelname, 32),
                source=_bounded_text(record.name, 256),
                message=_bounded_text(message, self._max_entry_bytes // 2),
                event_kind=event_kind,
                context=context,
                text=_bounded_text(text, 4096) if text is not None else None,
                text_truncated=text is not None and len(text.encode("utf-8", errors="replace")) > 4096,
            )
            self._next_id += 1
            size = len(json.dumps(asdict(entry), ensure_ascii=False).encode("utf-8"))
            if size > self._max_entry_bytes:
                return  # Never retain an entry exceeding either byte budget.
            self._entries.append((entry, size))
            self._bytes += size
            while len(self._entries) > self._max_entries or self._bytes > self._max_bytes:
                _, removed_size = self._entries.popleft()
                self._bytes -= removed_size

    def recent(self, *, after_id: int = 0, limit: int = 200) -> list[dict[str, object]]:
        with self._lock:
            entries = [entry for entry, _ in self._entries if entry.id > after_id]
            return [asdict(entry) for entry in entries[:limit]]

    def activity(self, *, after_id: int = 0, limit: int = 200) -> dict:
        entries = self.recent(after_id=after_id, limit=limit)
        return {"entries": [projected for entry in entries if (projected := project_activity(entry))],
                "next_after_id": entries[-1]["id"] if entries else after_id}


LIFECYCLE_EVENTS = {
    "twitch.subscribe", "twitch.connected", "twitch.recovered", "twitch.disconnected",
    "twitch.auth_required", "twitch.failed", "twitch.shutdown", "twitch.start",
    "twitch.stop", "twitch.reconnect", "operation.mode", "operation.stream",
    "operation.poll", "operation.failed",
}
ACTIVITY_EVENTS = {
    "command.input", "command.invoke", "command.outcome", "command.complete", "command.cooldown",
    "chat.send", "chat.outgoing", "ai.request_start", "ai.request_finish",
    "ai.fallback", "ai.failure", "ai.result", "ai_user_blocked",
    "chat.correlation", "chat.filtered", "twitch.socket",
}
CORRELATION_CONTEXT_FIELDS = {
    "event_id", "source", "outcome", "reason", "remaining_seconds", "drop_count", "pending_count",
    "duplicate_origin", "duplicate_delivery", "duplicate_age_seconds",
}


def socket_diagnostic_context(context: dict) -> dict:
    """Fixed operational fields only, safe for authenticated activity and stderr."""
    allowed = {
        "source": {"lifecycle"}, "stage": {"connection_lifecycle"},
        "outcome": {"connection_observation", "close_ignored"},
        "connection_state": {"unknown", "connecting", "connected", "reconnecting", "stopped", "auth_required", "failed"},
        "reason": {"socket_welcome", "active_socket_closed", "unwelcomed_socket", "superseded_socket",
                   "client_closing", "client_closed", "closed_client_ingress", "replaced_client_ingress",
                   "inactive_session_ingress", "state_connecting", "state_connected", "state_reconnecting",
                   "state_stopped", "state_auth_required", "state_failed"},
    }
    result = {key: value for key, value in context.items()
              if key in allowed and isinstance(value, str) and value in allowed[key]}
    for key in ("client_instance", "send_session_ref", "socket_ref", "active_socket_ref", "transport_ref"):
        value = context.get(key)
        if isinstance(value, str) and re.fullmatch(r"[a-f0-9]{12}(?:[a-f0-9]{4})?", value):
            result[key] = value
    for key in ("current_client", "send_active"):
        if type(context.get(key)) is bool:
            result[key] = context[key]
    for key in ("sdk_socket_count", "sdk_reconnect_count", "event_count"):
        value = context.get(key)
        if type(value) is int and 0 <= value <= 1_000_000_000:
            result[key] = value
    return result


def project_activity(entry: dict) -> dict | None:
    """Both transports expose the same allowlisted projection, never raw log prose."""
    kind = entry.get("event_kind")
    if kind in LIFECYCLE_EVENTS:
        return {**entry, "source": "lifecycle", "context": {}, "text": None,
                "text_truncated": False, "message": "Twitch lifecycle: " + kind}
    if kind not in ACTIVITY_EVENTS:
        return None
    context = {key: value for key, value in entry["context"].items()
               if key in EVENT_CONTEXT_ATTRIBUTES.values()}
    if kind == "chat.correlation":
        context = {key: value for key, value in context.items() if key in CORRELATION_CONTEXT_FIELDS}
    if kind == "twitch.socket":
        context = socket_diagnostic_context(context)
    return {**entry, "context": context,
            "message": f"{kind} outcome={context.get('outcome', 'unknown')}",
            "text": entry.get("text") if kind in {"command.input", "chat.outgoing"} else None}


class OperatorActivityHandler(logging.Handler):
    """Retain only panel events; stderr lifecycle filtering is independent."""

    def __init__(self, buffer: RecentLogBuffer) -> None:
        super().__init__()
        self._buffer = buffer

    def emit(self, record: logging.LogRecord) -> None:
        if _private_logs_suppressed():
            return
        if getattr(record, "event_kind", None) in ACTIVITY_EVENTS | LIFECYCLE_EVENTS:
            self._buffer.append(record, "")


class RecentLogHandler(logging.Handler):
    def __init__(self, buffer: RecentLogBuffer) -> None:
        super().__init__()
        self._buffer = buffer

    def emit(self, record: logging.LogRecord) -> None:
        if _private_logs_suppressed():
            return
        try:
            message = record.getMessage()
            if record.exc_info:
                formatter = self.formatter or logging.Formatter()
                message = f"{message}\n{formatter.formatException(record.exc_info)}"
            self._buffer.append(record, message)
        except Exception:
            self.handleError(record)


_recent_log_buffer = RecentLogBuffer()
_recent_log_handler = OperatorActivityHandler(_recent_log_buffer)


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    root_logger = logging.getLogger()
    if _recent_log_handler not in root_logger.handlers:
        root_logger.addHandler(_recent_log_handler)
    for handler in root_logger.handlers:
        if not any(isinstance(item, PrivacyLogFilter) for item in handler.filters):
            handler.addFilter(PrivacyLogFilter())
    logging.getLogger("twitchio").setLevel(logging.CRITICAL + 1)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def get_recent_log_buffer() -> RecentLogBuffer:
    return _recent_log_buffer
