"""Send/EventSub races use stable IDs, never message text or blanket identity."""

import asyncio
from types import SimpleNamespace

import pytest

from app.twitch.message_correlation import ChatMessageCorrelation
from twitchio.exceptions import MessageRejectedError


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
