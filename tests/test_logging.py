"""Tests for the bounded log history exposed to the desktop UI."""

import logging

from app.utils.logging import RecentLogBuffer, RecentLogHandler


def emit(
    handler: RecentLogHandler,
    message: str,
    level: int = logging.INFO,
    **extra: object,
) -> None:
    record = logging.LogRecord(
        name="tests.source",
        level=level,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )
    for name, value in extra.items():
        setattr(record, name, value)
    handler.emit(record)


def test_recent_log_buffer_discards_oldest_entries() -> None:
    buffer = RecentLogBuffer(max_entries=2)
    handler = RecentLogHandler(buffer)

    emit(handler, "first")
    emit(handler, "second", logging.WARNING)
    emit(handler, "third", logging.ERROR)

    entries = buffer.recent()

    assert [entry["message"] for entry in entries] == ["second", "third"]
    assert entries[0]["level"] == "WARNING"
    assert entries[0]["source"] == "tests.source"
    assert entries[0]["timestamp"].endswith("Z")


def test_recent_log_buffer_reads_only_entries_after_cursor() -> None:
    buffer = RecentLogBuffer(max_entries=5)
    handler = RecentLogHandler(buffer)
    emit(handler, "first")
    emit(handler, "second")
    emit(handler, "third")

    entries = buffer.recent(after_id=1, limit=1)

    assert len(entries) == 1
    assert entries[0]["id"] == 2
    assert entries[0]["message"] == "second"


def test_recent_log_buffer_exposes_only_whitelisted_semantic_context() -> None:
    buffer = RecentLogBuffer(max_entries=5)
    handler = RecentLogHandler(buffer)

    emit(
        handler,
        "Command cooldown rejected",
        event_kind="command.cooldown",
        event_command="ask",
        event_username="viewer",
        event_retry_after_seconds=12.5,
        event_secret="must-not-be-exposed",
    )

    entry = buffer.recent()[0]
    assert entry["event_kind"] == "command.cooldown"
    assert entry["context"] == {
        "username": "viewer",
        "command": "ask",
        "retry_after_seconds": 12.5,
    }
    assert "must-not-be-exposed" not in str(entry)
