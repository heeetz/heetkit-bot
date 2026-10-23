"""Tests for the bounded log history exposed to the desktop UI."""

import logging
import json
import asyncio
import pytest

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


def test_utf8_history_is_bounded_by_bytes_and_count_with_oversized_metadata():
    buffer = RecentLogBuffer(max_entries=5, max_bytes=2000, max_entry_bytes=1000)
    handler = RecentLogHandler(buffer)
    for _ in range(20):
        emit(handler, "😀" * 10000, event_kind="chat.outgoing", event_message_id="x" * 100000)
    # An individual oversized entry is dropped without displacing useful history.
    emit(handler, "ok")
    for _ in range(10):
        emit(handler, "😀" * 10000)
    entries = buffer.recent()
    sizes = [len(json.dumps(entry, ensure_ascii=False).encode("utf-8")) for entry in entries]
    assert 0 < len(entries) <= 5
    assert sum(sizes) <= 2000
    assert max(sizes) <= 1000
    assert all(len(entry["message"].encode("utf-8")) <= 500 for entry in entries)


def test_operator_metadata_bounds_scalars_and_excludes_unapproved_payloads():
    from app.utils.logging import event_metadata, operator_event_scope

    with operator_event_scope(channel="channel", request_id="a" * 32):
        metadata = event_metadata("ai.result", message_id="😀" * 1000,
                                  secret="SECRET", reasoning={"text": "PRIVATE"})
    assert metadata["event_request_id"] == "a" * 32
    assert len(metadata["event_event_id"]) == 32
    assert len(metadata["event_message_id"].encode("utf-8")) <= 512
    assert "SECRET" not in str(metadata) and "PRIVATE" not in str(metadata)
    assert "event_request_id" not in event_metadata("later")


@pytest.mark.asyncio
async def test_private_operator_events_do_not_leak_or_suppress_concurrent_requests():
    from app.utils.logging import operator_event, operator_event_scope, privacy_log_scope, PrivacyLogFilter
    buffer = RecentLogBuffer()
    logger = logging.getLogger("tests.operator.privacy")
    handler = RecentLogHandler(buffer)
    handler.addFilter(PrivacyLogFilter())
    logger.addHandler(handler)
    old_level = logger.level
    logger.setLevel(logging.INFO)
    entered, release = asyncio.Event(), asyncio.Event()
    async def private():
        with privacy_log_scope(True), operator_event_scope(request_id="PRIVATE", username="PRIVATE"):
            operator_event(logger, "command.input", "received")
            entered.set()
            await release.wait()
            operator_event(logger, "chat.outgoing", "confirmed_send", message_id="PRIVATE")
    try:
        task = asyncio.create_task(private())
        await entered.wait()
        with operator_event_scope(request_id="public", username="viewer"):
            operator_event(logger, "command.input", "received")
            release.set()
            await task
            operator_event(logger, "chat.outgoing", "confirmed_send", message_id="permitted")
        entries = buffer.recent()
        assert len(entries) == 2
        assert all(entry["context"]["request_id"] == "public" for entry in entries)
        assert "PRIVATE" not in str(entries)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)
