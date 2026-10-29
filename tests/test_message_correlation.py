"""Send/EventSub races use stable IDs, never message text or blanket identity."""

import asyncio
import logging
from types import SimpleNamespace

import pytest

from app.twitch.message_correlation import ChatMessageCorrelation
from twitchio.exceptions import MessageRejectedError
from app.utils.logging import OperatorActivityHandler, RecentLogBuffer, operator_event_scope, privacy_log_scope


async def event_loop_turns():
    for _ in range(8):
        await asyncio.sleep(0)


def correlation_activity():
    buffer = RecentLogBuffer()
    handler = OperatorActivityHandler(buffer)
    logger = logging.getLogger("app.headless.chat")
    logger.addHandler(handler)
    return buffer, handler, logger


@pytest.mark.asyncio
async def test_concurrent_send_race_identical_manual_text_and_channel_account_isolation():
    correlation = ChatMessageCorrelation()
    entered, release = asyncio.Event(), asyncio.Event()

    async def send(content):
        entered.set()
        await release.wait()
        return SimpleNamespace(id=content, sent=True)

    sends = [asyncio.create_task(correlation.send("bot", "channel", send, value))
             for value in ("one", "two")]
    await entered.wait()
    echo = asyncio.create_task(correlation.is_outgoing("bot", "channel", ("two",)))
    manual = asyncio.create_task(correlation.is_outgoing("bot", "channel", ("manual",)))
    await asyncio.sleep(0)
    assert not echo.done() and not manual.done()
    release.set()
    await asyncio.gather(*sends)
    assert await echo
    assert not await manual
    assert not await correlation.is_outgoing("other-bot", "channel", ("two",))
    assert not await correlation.is_outgoing("bot", "other-channel", ("two",))
    assert await correlation.is_outgoing("bot", "channel", ("copy", "one"))
    assert not correlation.pending


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["reject", "error", "missing", "cancel", "timeout"])
async def test_failed_sends_release_waiters_without_text_matching(failure):
    now = [0.0]
    correlation = ChatMessageCorrelation(clock=lambda: now[0], ttl=60, send_timeout=.01)
    entered = asyncio.Event()

    async def send(content):
        entered.set()
        if failure == "reject":
            return SimpleNamespace(sent=False, id="rejected")
        if failure == "error":
            raise OSError("synthetic lost HTTP response")
        if failure == "missing":
            return None
        await asyncio.Event().wait()

    task = asyncio.create_task(correlation.send("bot", "channel", send, "!ask question"))
    await entered.wait()
    incoming = asyncio.create_task(correlation.is_outgoing("bot", "channel", ("event",)))
    if failure == "cancel":
        task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert await incoming is (failure != "reject")
    assert not correlation.pending
    assert not await correlation.is_outgoing("viewer", "channel", ("event",))
    now[0] = 60
    assert not await correlation.is_outgoing("bot", "channel", ("manual",))


@pytest.mark.asyncio
async def test_caches_bound_expire_and_survive_transport_rebind():
    from app.services.twitch import TwitchAPIService

    now = [0.0]
    service = TwitchAPIService()
    service.chat_messages = correlation = ChatMessageCorrelation(limit=2, ttl=60, clock=lambda: now[0])
    async def send(content):
        return SimpleNamespace(id=content, sent=True)
    for message_id in ("one", "two", "three"):
        assert correlation.reserve("bot", "channel", message_id)
        await correlation.send("bot", "channel", send, message_id)
    service.bind(object(), "channel", "bot")
    assert len(correlation.seen) == len(correlation.outgoing) == 2
    assert not correlation.reserve("bot", "channel", "three")
    assert await correlation.is_outgoing("bot", "channel", ("three",))
    now[0] = 60
    assert correlation.reserve("bot", "channel", "three")
    assert not await correlation.is_outgoing("bot", "channel", ("three",))


@pytest.mark.asyncio
async def test_cancelled_ingress_does_not_cancel_send_completion():
    correlation = ChatMessageCorrelation()
    entered, release = asyncio.Event(), asyncio.Event()
    async def send(content):
        entered.set()
        await release.wait()
        return SimpleNamespace(id="sent", sent=True)
    task = asyncio.create_task(correlation.send("bot", "channel", send, "response"))
    await entered.wait()
    ingress = asyncio.create_task(correlation.is_outgoing("bot", "channel", ("sent",)))
    await asyncio.sleep(0)
    ingress.cancel()
    await asyncio.gather(ingress, return_exceptions=True)
    release.set()
    await task
    assert await correlation.is_outgoing("bot", "channel", ("sent",))


@pytest.mark.asyncio
async def test_oversized_ids_cannot_expand_retained_cache_bytes():
    correlation = ChatMessageCorrelation(limit=2)
    huge_id = "😀" * 256
    assert correlation.reserve("bot", "channel", huge_id)
    assert not correlation.seen

    async def send(_):
        return SimpleNamespace(id=huge_id, sent=True)

    await correlation.send("bot", "channel", send, "response")
    assert not correlation.outgoing
    assert await correlation.is_outgoing("bot", "channel", ("unknown",))
    with pytest.raises(ValueError):
        await correlation.send(huge_id, "channel", send, "response")
    assert not correlation.pending


@pytest.mark.asyncio
async def test_sdk_rejection_is_failed_without_quarantine_or_private_error_text(caplog):
    from app.commands.registry import CommandContext
    from app.twitch.events import ChatAuthor, IncomingChatMessage
    import logging
    correlation = ChatMessageCorrelation()
    rejection = MessageRejectedError("PRIVATE exception", content="PRIVATE response", channel=None,
        message=SimpleNamespace(dropped_code="rate_limit", dropped_message="PRIVATE payload"))
    async def reject(_):
        raise rejection
    async def respond(content):
        return await correlation.send("bot", "channel", reject, content)
    message = IncomingChatMessage("channel", "!ping", ChatAuthor("viewer", "viewer"), respond)
    with caplog.at_level(logging.INFO):
        with pytest.raises(MessageRejectedError):
            await CommandContext(message, SimpleNamespace(), logging.getLogger(__name__)).reply("PRIVATE response")
    assert not await correlation.is_outgoing("bot", "channel", ("manual",))
    assert not correlation.pending and not correlation.uncertain_until
    outcomes = [record.event_outcome for record in caplog.records
                if getattr(record, "event_kind", None) == "chat.outgoing"]
    assert outcomes == ["failed_send"]
    assert "PRIVATE" not in caplog.text


@pytest.mark.asyncio
async def test_pause_drops_are_sanitized_aggregated_and_expire_without_new_input(monkeypatch, caplog):
    loop = asyncio.get_running_loop()
    now = [loop.time()]
    monkeypatch.setattr(loop, "time", lambda: now[0])
    correlation = ChatMessageCorrelation(clock=lambda: now[0])
    buffer, handler, logger = correlation_activity()
    caplog.set_level(logging.INFO)
    async def missing(_):
        return None
    try:
        with operator_event_scope(username="PRIVATE", channel="PRIVATE", request_id="PRIVATE",
                                  input_message_id="PRIVATE", command="PRIVATE"):
            await correlation.send("PRIVATE-account", "PRIVATE-channel", missing, "PRIVATE response")
        for _ in range(100):
            assert await correlation.is_outgoing("PRIVATE-account", "PRIVATE-channel", ("PRIVATE input",))
        events = buffer.activity()["entries"]
        assert [e["context"]["outcome"] for e in events] == ["input_paused", "input_dropped"]
        assert events[0]["context"]["reason"] == "missing_send_result"
        assert events[1]["context"]["remaining_seconds"] == 600
        assert events[1]["context"]["drop_count"] == 1
        now[0] += 5
        assert await correlation.is_outgoing("PRIVATE-account", "PRIVATE-channel", ("another",))
        assert buffer.activity()["entries"][-1]["context"]["drop_count"] == 101
        now[0] += 594.9
        await event_loop_turns()
        assert correlation.uncertain_until
        now[0] += .1
        await event_loop_turns()
        assert not correlation.uncertain_until  # Timer, without another ingress event.
        recovered = buffer.activity()["entries"][-1]["context"]
        assert recovered["outcome"] == "input_resumed"
        assert recovered["reason"] == "quarantine_expired"
        assert recovered["remaining_seconds"] == 0 and recovered["drop_count"] == 101
        assert "PRIVATE" not in str(buffer.activity())
        assert not correlation._expiry_timers and not correlation._paused_drops
    finally:
        logger.removeHandler(handler)


@pytest.mark.asyncio
async def test_extension_cancels_old_expiry_and_keeps_quarantine_across_rebind(monkeypatch, caplog):
    from app.services.twitch import TwitchAPIService
    loop = asyncio.get_running_loop()
    now = [loop.time()]
    monkeypatch.setattr(loop, "time", lambda: now[0])
    service = TwitchAPIService()
    service.chat_messages = correlation = ChatMessageCorrelation(ttl=60, clock=lambda: now[0])
    caplog.set_level(logging.INFO)
    async def missing(_):
        return None
    await correlation.send("bot", "channel", missing, "response")
    original_timer = correlation._expiry_timers[("bot", "channel")]
    now[0] += 20
    await correlation.send("bot", "channel", missing, "response")
    assert original_timer.cancelled()
    service.bind(object(), "channel", "bot")
    now[0] += 40
    await event_loop_turns()
    assert await correlation.is_outgoing("bot", "channel", ("manual",))
    assert not any(getattr(r, "event_outcome", None) == "input_resumed" for r in caplog.records)
    now[0] += 20
    await event_loop_turns()
    assert not correlation.uncertain_until
    assert not await correlation.is_outgoing("bot", "channel", ("manual",))


@pytest.mark.asyncio
@pytest.mark.parametrize("failure,reason", [("cancel", "send_cancelled"), ("timeout", "send_timeout"),
                                         ("network", "send_error")])
async def test_pause_reasons_preserve_uncertain_send_classification(failure, reason, caplog):
    caplog.set_level(logging.INFO)
    correlation = ChatMessageCorrelation(send_timeout=.01)
    entered = asyncio.Event()
    async def send(_):
        entered.set()
        if failure == "network":
            raise OSError("PRIVATE error")
        await asyncio.Event().wait()
    task = asyncio.create_task(correlation.send("bot", "channel", send, "PRIVATE response"))
    await entered.wait()
    if failure == "cancel":
        task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    paused = [r for r in caplog.records if getattr(r, "event_outcome", None) == "input_paused"]
    assert len(paused) == 1 and paused[0].event_reason == reason
    assert await correlation.is_outgoing("bot", "channel", ("manual",))
    assert not await correlation.is_outgoing("another-bot", "channel", ("manual",))
    assert "PRIVATE" not in caplog.text


@pytest.mark.asyncio
async def test_pending_wait_echo_and_replay_decisions_are_bounded_without_changing_results(caplog):
    caplog.set_level(logging.INFO)
    correlation = ChatMessageCorrelation(limit=2)
    entered, release = asyncio.Event(), asyncio.Event()
    async def send(_):
        entered.set()
        await release.wait()
        return SimpleNamespace(id="sent", sent=True)
    task = asyncio.create_task(correlation.send("bot", "channel", send, "response"))
    await entered.wait()
    manual = asyncio.create_task(correlation.is_outgoing("bot", "channel", ("manual",)))
    await event_loop_turns()
    assert not manual.done()
    waiting = [r for r in caplog.records if getattr(r, "event_outcome", None) == "input_waiting"]
    assert len(waiting) == 1 and waiting[0].event_reason == "pending_send"
    assert waiting[0].event_pending_count == 1
    release.set()
    await task
    assert not await manual
    for _ in range(100):
        assert await correlation.is_outgoing("bot", "channel", ("sent",))
    assert correlation.reserve("bot", "channel", "replay")
    for _ in range(100):
        assert not correlation.reserve("bot", "channel", "replay")
    dropped = [r for r in caplog.records if getattr(r, "event_outcome", None) == "input_dropped"]
    assert [r.event_reason for r in dropped] == ["outgoing_message_id", "replay"]
    assert len(correlation._decisions) <= correlation.limit


@pytest.mark.asyncio
async def test_diagnostic_timers_and_counters_respect_cache_bound_and_request_privacy(monkeypatch, caplog):
    loop = asyncio.get_running_loop()
    now = [loop.time()]
    monkeypatch.setattr(loop, "time", lambda: now[0])
    correlation = ChatMessageCorrelation(limit=2, ttl=60, clock=lambda: now[0])
    buffer, handler, logger = correlation_activity()
    caplog.set_level(logging.INFO)
    async def missing(_):
        return None
    try:
        with privacy_log_scope(True), operator_event_scope(username="PRIVATE"):
            await correlation.send("private", "channel", missing, "PRIVATE")
        now[0] += 60
        await event_loop_turns()
        assert buffer.activity()["entries"] == []  # Includes the timer callback.
        for account in ("one", "two", "three"):
            await correlation.send(account, "channel", missing, "response")
        assert len(correlation.uncertain_until) == len(correlation._expiry_timers) == len(correlation._paused_drops) == 2
        assert ("one", "channel") not in correlation.uncertain_until
        assert not await correlation.is_outgoing("one", "channel", ("manual",))
        assert buffer.activity()["entries"][-1]["context"]["reason"] == "tracking_evicted"
        assert "PRIVATE" not in str(buffer.activity())
    finally:
        logger.removeHandler(handler)


def test_replay_origin_metadata_expires_and_remains_bounded(caplog):
    caplog.set_level(logging.INFO)
    now = [100.0]
    correlation = ChatMessageCorrelation(limit=2, ttl=10, clock=lambda: now[0])
    for value in ('one', 'two', 'three'):
        assert correlation.reserve('account', 'channel', value, origin=('client-a', 'socket-a'))
    assert len(correlation._ingress_origins) == len(correlation.seen) == 2
    assert not correlation.reserve('account', 'channel', 'three', origin=('client-b', 'socket-a'))
    record = caplog.records[-1]
    assert record.event_duplicate_origin == 'different_client'
    now[0] += 10
    assert correlation.reserve('account', 'channel', 'three', origin=('client-b', 'socket-b'))
    assert len(correlation._ingress_origins) == 1
