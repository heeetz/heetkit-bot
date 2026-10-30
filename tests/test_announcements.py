"""Synthetic schedules: monotonic time, no Twitch accounts or wall-clock waits."""

import asyncio
import json
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from twitchio.exceptions import HTTPException

from app.announcements import AnnouncementScheduler, AnnouncementStore, parse_announcements
from app.services.twitch import TwitchAPIService
from app.twitch.events import ChatAuthor, IncomingChatMessage
from app.utils.output_limiter import OutputLimiter


def entry(**changes):
    return {"id": str(uuid4()), "name": "Community", "enabled": True, "messages": ["Join our community"],
        "message_mode": "single", "interval_seconds": 60, "min_messages": 0,
        "stream_availability": "anytime", "delivery_mode": "regular", **changes}


@pytest.fixture
async def rig(tmp_path):
    now = [0.0]
    store = AnnouncementStore(tmp_path / "announcements.json")
    store.save([entry()])
    responder = AsyncMock(return_value=SimpleNamespace(id="sent", sent=True))
    client = SimpleNamespace(create_partialuser=lambda channel: SimpleNamespace(send_message=responder, send_announcement=responder))
    twitch = TwitchAPIService(output_limiter=OutputLimiter(interval=0, clock=lambda: now[0]))
    twitch.bind(client, "200", "100", channel_name="channel")
    state = SimpleNamespace(server_runtime=False, server_stream_status=None)
    scheduler = AnnouncementScheduler(store, twitch, SimpleNamespace(), state,
        clock=lambda: now[0], utcnow=lambda: datetime.fromtimestamp(now[0], timezone.utc), choose=lambda values: values[-1])
    twitch.get_broadcaster_live = AsyncMock(return_value=True)
    twitch.close_stream_monitor = AsyncMock()
    twitch.set_chat_ready(client, True)
    def human(**changes):
        message = IncomingChatMessage("channel", "ordinary chat", ChatAuthor("300", "viewer"), AsyncMock(),
                                      send_session=twitch.chat_session(client))
        twitch.record_human_message(replace(message, **changes))
    def save(**changes):
        store.save([{**store.list()[0].to_json(), **changes}])
        scheduler.reset()
    yield SimpleNamespace(now=now, store=store, scheduler=scheduler, twitch=twitch, client=client,
                          responder=responder, state=state, human=human, save=save)
    await scheduler.close()
    await twitch.unbind(client)


async def test_full_interval_no_backlog_restart_and_random_choice(rig):
    r = rig
    r.save(message_mode="random", messages=["one", "two"])
    r.now[0] = 59
    await r.scheduler.tick()
    r.responder.assert_not_awaited()
    r.now[0] = 600  # ten missed deadlines still yield only one ordinary send
    await r.scheduler.tick()
    r.responder.assert_awaited_once_with(message="two", sender="100", token_for="100")
    snapshot = r.scheduler.snapshot()[0]["status"]
    assert snapshot["last_outcome"] == "sent"
    assert snapshot["last_sent_at"] == "1970-01-01T00:10:00+00:00"
    assert snapshot["next_run_at"] == "1970-01-01T00:11:00+00:00"
    await r.scheduler.tick()
    assert r.responder.await_count == 1


@pytest.mark.parametrize("delivery,terminal", [(True, "sent"), (False, "failed"), (None, "uncertain"), ("timeout", "uncertain")])
async def test_aggregate_announcement_attempt_has_one_delivery_outcome(rig, tmp_path, delivery, terminal):
    from app.analytics import Analytics
    analytics = Analytics(tmp_path / "synthetic.analytics.sqlite3")
    await analytics.start()
    r = rig
    r.scheduler.settings.twitch_channel_user_id = "200"
    r.twitch.analytics = analytics
    if delivery == "timeout":
        r.responder.side_effect = TimeoutError()
    else:
        r.responder.return_value = SimpleNamespace(sent=delivery) if delivery is not None else None
    try:
        r.now[0] = 60
        await r.scheduler.tick()
        while analytics.queue:
            await analytics.flush()
        values = {row["metric"]: row["value"] for row in (await analytics.snapshot("200"))["rows"]}
        assert values == {"announcement.attempts": 1, "announcement." + terminal: 1}
    finally:
        r.twitch.analytics = None
        await analytics.close()
    # A fresh scheduler loads configuration only, no deadlines/delivery/activity.
    restarted = AnnouncementScheduler(AnnouncementStore(r.store._path), r.twitch, SimpleNamespace(), r.state,
                                      clock=lambda: r.now[0])
    restarted.reset()
    try:
        await restarted.tick()
        assert r.responder.await_count == 1
        r.now[0] += 60
        await restarted.tick()
        assert r.responder.await_count == 2
    finally:
        await restarted.close()


async def test_activity_consumed_on_every_check_and_own_bot_never_counts(rig):
    r = rig
    r.save(min_messages=2)
    r.human(author=ChatAuthor("100", "ownbot"))
    r.human(author=ChatAuthor("300", "botbadge", is_bot=True))
    r.human(is_outgoing=True)
    r.human(channel="oldchannel")
    r.human(send_session=None)
    assert r.twitch.human_messages == 0
    r.human()
    r.now[0] = 60
    await r.scheduler.tick()
    assert r.scheduler.snapshot()[0]["status"]["last_outcome"] == "skipped_activity"
    r.human()
    r.now[0] = 120
    await r.scheduler.tick()
    r.responder.assert_not_awaited()  # activity from different windows cannot accumulate
    r.human()
    r.human()
    r.now[0] = 180
    await r.scheduler.tick()
    assert r.responder.await_count == 1
    assert r.scheduler.snapshot()[0]["status"]["eligible_messages"] == 0


@pytest.mark.parametrize("server", [False, True])
@pytest.mark.parametrize("availability,observation,expected", [
    ("anytime", "unknown", True), ("live_only", "unknown", False),
    ("offline_only", "unknown", False), ("live_only", "offline", False),
    ("offline_only", "live", False), ("live_only", "live", True), ("offline_only", "offline", True),
])
async def test_both_hosts_stream_gates_fail_closed(rig, server, availability, observation, expected):
    r = rig
    r.save(stream_availability=availability)
    r.state.server_runtime = server
    r.state.server_stream_status = lambda: observation
    r.scheduler._stream_status = observation
    r.scheduler._checked_at = 0
    r.scheduler._next_poll = 1000
    r.now[0] = 60
    await r.scheduler.tick()
    assert bool(r.responder.await_count) is expected
    assert r.scheduler.snapshot()[0]["status"]["last_outcome"] == ("sent" if expected else "skipped_stream")
    r.twitch.get_broadcaster_live.assert_not_awaited()


async def test_desktop_poll_expiry_failure_and_late_channel_result(rig):
    r = rig
    r.save(stream_availability="offline_only")
    r.twitch.get_broadcaster_live.return_value = False
    await r.scheduler.tick()
    await r.scheduler._poll
    assert r.scheduler.stream_status() == "offline"
    r.now[0] = 135
    assert r.scheduler.stream_status() == "unknown"
    r.twitch.get_broadcaster_live.side_effect = OSError("private response sentinel")
    await r.scheduler.tick()
    await r.scheduler._poll
    assert r.scheduler.stream_status() == "unknown"
    assert r.scheduler.snapshot()[0]["status"]["last_outcome"] == "skipped_stream"
    r.twitch.close_stream_monitor.assert_awaited_once()
    entered, release = asyncio.Event(), asyncio.Event()
    async def late(_settings):
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            await release.wait()  # even an uncancellable old result cannot publish
        return False
    r.twitch.get_broadcaster_live = late
    r.now[0] = 200
    await r.scheduler.tick()
    await entered.wait()
    pending = r.scheduler._poll
    r.twitch.set_chat_ready(r.client, False)
    r.twitch.set_chat_ready(r.client, True)
    release.set()
    await pending
    assert r.scheduler.stream_status() == "unknown"


async def test_reconnect_stop_switch_and_edits_reset_interval_and_activity(rig):
    r = rig
    r.save(min_messages=1)
    r.human()
    r.now[0] = 59
    r.twitch.set_chat_ready(r.client, False)
    assert r.scheduler.snapshot()[0]["status"]["next_run_at"] is None
    r.twitch.set_chat_ready(r.client, True)
    assert r.twitch.human_messages == 0
    r.now[0] = 60
    await r.scheduler.tick()
    r.responder.assert_not_awaited()
    r.now[0] = 119
    await r.scheduler.tick()
    assert r.scheduler.snapshot()[0]["status"]["last_outcome"] == "skipped_activity"
    r.human()
    r.save(messages=["edited"])
    r.now[0] = 179
    await r.scheduler.tick()
    r.responder.assert_not_awaited()
    r.human()
    r.twitch.stop_chat()
    r.now[0] = 1000
    await r.scheduler.tick()
    r.responder.assert_not_awaited()
    other = AsyncMock(return_value=SimpleNamespace(sent=True, id="new"))
    client = SimpleNamespace(create_partialuser=lambda channel: SimpleNamespace(send_message=other))
    r.twitch.bind(client, "400", "100", channel_name="newchannel")
    r.twitch.set_chat_ready(client, True)
    r.now[0] = 1060
    await r.scheduler.tick()
    other.assert_not_awaited()
    r.save(min_messages=0)
    r.now[0] = 1120
    await r.scheduler.tick()
    other.assert_awaited_once_with(message="edited", sender="100", token_for="100")
    await r.twitch.unbind(client)


@pytest.mark.parametrize("delivery_mode", ["regular", "highlighted"])
async def test_inflight_cancelled_on_stop_and_no_concurrent_pileup(rig, delivery_mode):
    r = rig
    started, release = asyncio.Event(), asyncio.Event()
    active = maximum = 0
    async def blocked(**kwargs):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        started.set()
        try:
            await release.wait()
            return SimpleNamespace(sent=True)
        finally:
            active -= 1
    r.responder.side_effect = blocked
    r.store.save([entry(delivery_mode=delivery_mode), entry(delivery_mode=delivery_mode)])
    r.scheduler.reset()
    r.now[0] = 60
    first = asyncio.create_task(r.scheduler.tick())
    await started.wait()
    second = asyncio.create_task(r.scheduler.tick())
    r.twitch.stop_chat()
    release.set()
    await asyncio.gather(first, second)
    assert maximum == 1 and active == 0
    assert r.responder.await_count == 1
    assert all(row["status"]["next_run_at"] is None for row in r.scheduler.snapshot())
    assert r.scheduler.snapshot()[0]["status"]["last_outcome"] == "cancelled"


@pytest.mark.parametrize("result,outcome", [(False, "not_confirmed"), (None, "not_confirmed"),
                                          (OSError("private failure"), "failed"), (True, "sent")])
async def test_delivery_outcomes_without_retry_and_preserved_history(rig, result, outcome, caplog):
    r = rig
    if isinstance(result, Exception):
        r.responder.side_effect = result
    else:
        r.responder.return_value = None if result is None else SimpleNamespace(sent=result)
    r.now[0] = 60
    await r.scheduler.tick()
    await r.scheduler.tick()
    assert r.responder.await_count == 1
    assert r.scheduler.snapshot()[0]["status"]["last_outcome"] == outcome
    assert "private failure" not in caplog.text
    r.twitch.stop_chat()
    assert r.scheduler.snapshot()[0]["status"]["last_outcome"] == outcome


@pytest.mark.parametrize("server", [False, True])
@pytest.mark.parametrize("error_status,outcome", [(None, "sent"), (401, "authorization_required"),
    (403, "permission_denied"), (429, "failed"), (500, "failed")])
async def test_highlighted_delivery_both_hosts_without_regular_fallback(rig, server, error_status, outcome, caplog):
    r = rig
    r.save(delivery_mode="highlighted")
    r.state.server_runtime = server
    r.responder.return_value = None  # Twitch's successful 204 has no result body.
    if error_status:
        r.responder.side_effect = HTTPException("PRIVATE provider rejection", status=error_status, extra={})
    r.now[0] = 60
    await r.scheduler.tick()
    await r.scheduler.tick()
    r.responder.assert_awaited_once_with(moderator="100", message="Join our community", color="primary", token_for="100")
    status = r.scheduler.snapshot()[0]["status"]
    assert status["last_outcome"] == outcome
    assert bool(status["last_sent_at"]) is (outcome == "sent")
    assert not r.twitch.chat_messages.pending and not r.twitch.chat_messages.uncertain_until
    assert "PRIVATE" not in caplog.text


def test_legacy_announcement_defaults_to_regular_and_type_survives_reload(tmp_path):
    legacy = entry()
    legacy.pop("delivery_mode")
    path = tmp_path / "announcements.json"
    path.write_text(json.dumps({"version": 1, "announcements": [legacy]}), encoding="utf-8")
    store = AnnouncementStore(path)
    assert store.list()[0].delivery_mode == "regular"
    store.save([{**legacy, "delivery_mode": "highlighted"}])
    assert AnnouncementStore(path).list()[0].delivery_mode == "highlighted"


@pytest.mark.parametrize("delivery_mode", ["regular", "highlighted"])
async def test_disabled_schedules_and_shared_limiter(rig, delivery_mode):
    r = rig
    r.save(enabled=False, delivery_mode=delivery_mode)
    r.now[0] = 100
    await r.scheduler.tick()
    r.responder.assert_not_awaited()
    assert r.scheduler.snapshot()[0]["status"]["next_run_at"] is None
    r.save(enabled=True)
    r.twitch.output_limiter = OutputLimiter(interval=5, clock=lambda: r.now[0])
    r.now[0] = 160
    assert await r.twitch.chat_sender().reply("command output")
    await r.scheduler.tick()
    assert r.responder.await_count == 1
    assert r.scheduler.snapshot()[0]["status"]["last_outcome"] == "not_confirmed"


async def test_coincident_schedules_do_not_starve_behind_shared_limiter(rig):
    r = rig
    r.store.save([entry(messages=["first"]), entry(messages=["second"])])
    r.scheduler.reset()
    r.twitch.output_limiter = OutputLimiter(interval=5, clock=lambda: r.now[0])
    for deadline in (60, 120, 180):
        r.now[0] = deadline
        await r.scheduler.tick()
    assert [call.kwargs["message"] for call in r.responder.await_args_list] == ["first", "second", "first"]


async def test_worker_start_is_idempotent_and_close_drains_pending_output(rig):
    r = rig
    r.scheduler.start()
    worker = r.scheduler._worker
    r.scheduler.start()
    assert r.scheduler._worker is worker
    started = asyncio.Event()
    cancelled = asyncio.Event()
    async def pending(**kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    r.responder.side_effect = pending
    r.now[0] = 60
    # Worker has not run yet, so its first tick is exactly due at fake time 60.
    await started.wait()
    await r.scheduler.close()
    assert worker.done() and cancelled.is_set()
    assert not r.twitch._send_session.tasks
    assert r.scheduler.snapshot()[0]["status"]["next_run_at"] is None
    r.scheduler.start()
    assert r.scheduler._worker is worker


@pytest.mark.parametrize("changes", [
    {"interval_seconds": 59}, {"interval_seconds": 86401}, {"interval_seconds": True},
    {"interval_seconds": 60.5}, {"min_messages": -1}, {"min_messages": 1001},
    {"min_messages": True}, {"enabled": 1}, {"messages": []}, {"messages": ["x"] * 31},
    {"messages": ["x\ny"]}, {"messages": ["\x00"]}, {"messages": ["\ud800"]},
    {"messages": ["🙂" * 113]}, {"name": " "}, {"name": "x" * 81},
    {"message_mode": "burst"}, {"messages": ["one", "two"]},
    {"stream_availability": "unknown"}, {"unknown": "field"}, {"id": "bad"},
    {"delivery_mode": "announcepurple"}, {"delivery_mode": None}, {"delivery_mode": True},
])
def test_invalid_values_never_change_store(tmp_path, changes):
    store = AnnouncementStore(tmp_path / "announcements.json")
    original = entry()
    store.save([original])
    before = store._path.read_bytes()
    with pytest.raises(ValueError):
        store.save([{**original, **changes}])
    assert store._path.read_bytes() == before
    assert store.list()[0].to_json() == original


def test_atomic_persistence_ids_limits_corruption_and_future_recovery(tmp_path, monkeypatch):
    store = AnnouncementStore(tmp_path / "announcements.json")
    raw = entry()
    raw.pop("id")
    store.save([raw])
    saved = store.list()
    assert AnnouncementStore(store._path).list() == saved
    with pytest.raises(ValueError):
        parse_announcements([saved[0].to_json()] * 2)
    with pytest.raises(ValueError):
        parse_announcements([entry() for _ in range(51)])
    import app.announcements as module
    with monkeypatch.context() as scoped:
        scoped.setattr(module.os, "replace", lambda *args: (_ for _ in ()).throw(OSError("disk")))
        with pytest.raises(OSError):
            store.save([])
    assert store.list() == saved and AnnouncementStore(store._path).list() == saved
    assert not list(tmp_path.glob(".announcements-*"))
    for bad in ('{"version":2,"announcements":[]}', 'broken json'):
        store._path.write_text(bad)
        recovered = AnnouncementStore(store._path)
        assert not recovered.list()
        with pytest.raises(ValueError):
            recovered.save([])
        assert store._path.read_text() == bad


async def test_real_ingress_counts_only_current_eligible_unique_human_events(rig):
    import logging
    from app.services.ai_request_policy import PolicyDecision
    from app.twitch.client import TwitchChatBot

    r = rig
    services = SimpleNamespace(twitch=r.twitch, settings=SimpleNamespace(twitch_bot_user_id="100", command_prefix="!"),
        users=SimpleNamespace(upsert_seen=AsyncMock(), is_storage_opted_out=AsyncMock(return_value=True)),
        filter_manager=SimpleNamespace(filter_message=lambda text: text != "filtered"),
        ai_request_policy=SimpleNamespace(check=lambda args: PolicyDecision.IGNORE))
    dispatcher = SimpleNamespace(dispatch=AsyncMock(), is_ai_command=lambda incoming: incoming.content.startswith("!ask"))
    bot = SimpleNamespace(bot_id="100", _services=services, _dispatcher=dispatcher,
        _chat_messages=r.twitch.chat_messages, _logger=logging.getLogger(__name__),
        _closing_requested=False, _diagnostic_id="synthetic-current-client", _connection_event=Mock())
    # The fake bot identity must be the bound client for captured-session lookup.
    r.twitch.bind(bot, "200", "100", channel_name="channel")
    r.twitch.set_chat_ready(bot, True)
    def message(identifier, *, author="300", text="hello", badges=()):
        return SimpleNamespace(id=identifier, source_id=None, broadcaster=SimpleNamespace(id="200", name="channel"),
            chatter=SimpleNamespace(id=author, name="viewer", subscriber=False, vip=False, moderator=False,
                                    broadcaster=False, badges=badges), text=text, respond=AsyncMock())
    human = message("unique-human")
    await asyncio.gather(TwitchChatBot.event_message(bot, human), TwitchChatBot.event_message(bot, human))
    assert r.twitch.human_messages == 1
    for excluded in (message("self", author="100"), message("filtered", text="filtered"),
                     message("ignored-ai", text="!ask ignored"),
                     message("bot-badge", badges=[SimpleNamespace(set_id="bot", id="1")])):
        await TwitchChatBot.event_message(bot, excluded)
    assert r.twitch.human_messages == 1
    r.twitch.stop_chat()
    await TwitchChatBot.event_message(bot, message("stopped"))
    assert r.twitch.human_messages == 1
    bot._connection_event.assert_called_once_with("inactive_session_ingress")
    bot._connection_event.reset_mock()
    bot._closing_requested = True
    await TwitchChatBot.event_message(bot, message("closing"))
    bot._connection_event.assert_called_once_with("closed_client_ingress")
    assert r.twitch.human_messages == 1
    bot._closing_requested = False
    await r.twitch.unbind(bot)
    await TwitchChatBot.event_message(bot, message("retired"))
    bot._connection_event.assert_called_with("replaced_client_ingress")
    assert r.twitch.human_messages == 1
