"""Policy transitions against the real shared runtime and synthetic Twitch only."""

import asyncio
import json
import logging
from types import SimpleNamespace

import pytest

from app.app_settings import AppSettingsStore, OPERATION_MODES
from app.bot_runtime import BotRuntime
from app.config.settings import Settings
from app.operation_policy import OperationPolicy
from app.runtime_state import RuntimeState
from app.commands.registry import CommandDispatcher, CommandRegistry
from app.custom_commands import CustomCommandStore
from app.twitch.events import ChatAuthor, IncomingChatMessage
from app.utils.cooldown import CooldownManager


async def eventually(predicate):
    async def wait():
        while not predicate():
            await asyncio.sleep(0.001)
    await asyncio.wait_for(wait(), 2)


@pytest.fixture
async def rig(tmp_path, monkeypatch):
    state = RuntimeState(command_settings_path=tmp_path / "commands.json",
                         personality_settings_path=tmp_path / "personalities.json")
    calls = SimpleNamespace(active=0, maximum=0, starts=0, live=False, polls=0,
                            gate=None, stop_gate=None, closed=0, poll_times=[])

    async def live(settings):
        calls.polls += 1
        calls.poll_times.append(asyncio.get_running_loop().time())
        if calls.gate:
            await calls.gate.wait()
        if isinstance(calls.live, Exception):
            raise calls.live
        return calls.live

    async def close():
        calls.closed += 1

    async def noop():
        pass

    async def session(**kwargs):
        calls.active += 1
        calls.maximum = max(calls.maximum, calls.active)
        calls.starts += 1
        try:
            state.set_twitch_connection_state("connected")
            await kwargs["stop_event"].wait()
            if calls.stop_gate:
                await calls.stop_gate.wait()
        finally:
            calls.active -= 1

    app = SimpleNamespace(settings=Settings(_env_file=None, twitch_client_id="synthetic",
        twitch_client_secret="synthetic", twitch_bot_username="testbot", twitch_bot_user_id="100",
        twitch_channel="testchannel", twitch_channel_user_id="200"),
        services=SimpleNamespace(runtime_state=state, twitch=SimpleNamespace(
            get_broadcaster_live=live, close_stream_monitor=close)),
        dispatcher=object(), startup=noop, shutdown=noop)
    monkeypatch.setattr("app.bot_runtime.run_twitch_bot", session)
    runtime = BotRuntime(app, logging.getLogger("test.policy"), headless=True)
    store = AppSettingsStore(tmp_path / "app_settings.json")
    store.update_operation_mode("manual")
    policy = OperationPolicy(runtime, store, poll_interval=0.01, max_backoff=0.08,
                             request_timeout=0.2)
    await runtime.startup()
    await policy.start()
    try:
        yield policy, runtime, calls, state, store
    finally:
        if calls.stop_gate:
            calls.stop_gate.set()
        await policy.close()
        await runtime.shutdown()


@pytest.mark.parametrize("source", sorted(OPERATION_MODES))
@pytest.mark.parametrize("target", sorted(OPERATION_MODES))
async def test_all_mode_transitions_persist_without_duplicate_sessions(rig, source, target):
    policy, runtime, calls, state, store = rig
    calls.live = True
    policy.set_mode(source)
    await eventually(lambda: not policy.pending and runtime.bot_active == (source in {"always_on", "stream_only"}))
    policy.set_mode(target)
    await eventually(lambda: not policy.pending and runtime.bot_active == (target in {"always_on", "stream_only"}))
    assert AppSettingsStore(store._path).snapshot().startup.operation_mode == target
    assert calls.maximum <= 1
    if target == "disabled":
        with pytest.raises(ValueError):
            policy.connect()


async def test_stream_confirmation_unknown_retention_and_recovery(rig):
    policy, runtime, calls, state, _ = rig
    calls.gate = asyncio.Event()
    policy.set_mode("stream_only")
    await eventually(lambda: calls.polls == 1)
    assert not runtime.bot_active and policy.stream_status == "unknown"
    calls.live = True
    calls.gate.set()
    await eventually(lambda: policy.last_known_stream_status == "live")
    assert calls.starts == 0  # One observation never starts or stops a session.
    await eventually(lambda: calls.starts == 1)
    state.set_twitch_connection_state("reconnecting")
    calls.live = RuntimeError("private-token-provider-payload")
    await eventually(lambda: policy.stream_status == "unknown")
    await asyncio.sleep(0.04)
    assert runtime.bot_active and policy.desired_running
    assert policy.last_known_stream_status == "live"
    assert state.twitch_connection_state == "reconnecting" and calls.starts == 1
    assert "private-token" not in json.dumps(policy.snapshot())
    state.set_twitch_connection_state("connected")  # Existing TwitchIO recovery.
    calls.live = False
    await eventually(lambda: policy.stream_status == "offline")
    assert runtime.bot_active
    await eventually(lambda: not runtime.bot_active)
    calls.live = True
    await eventually(lambda: calls.starts == 2)
    assert calls.maximum == 1


async def test_monitor_failures_back_off_and_do_not_prove_offline(rig, caplog):
    policy, runtime, calls, _, _ = rig
    calls.live = RuntimeError("private-provider-sentinel")
    with caplog.at_level(logging.INFO):
        policy.set_mode("stream_only")
        await eventually(lambda: calls.polls >= 3)
        # Assert lower bounds only: Windows scheduling may wake checks late.
        assert calls.poll_times[1] - calls.poll_times[0] >= 0.018
        assert calls.poll_times[2] - calls.poll_times[1] >= 0.038
    assert not runtime.bot_active and policy.last_known_stream_status is None
    assert policy.stream_status == "unknown" and policy.last_checked_at
    assert "private-provider-sentinel" not in caplog.text


async def test_pending_poll_cannot_override_disabled_or_manual_intent(rig):
    policy, runtime, calls, _, _ = rig
    calls.live, calls.gate = True, asyncio.Event()
    policy.set_mode("stream_only")
    await eventually(lambda: calls.polls == 1)
    policy.set_mode("disabled")
    calls.gate.set()
    await asyncio.sleep(0.04)
    assert policy.mode == "disabled" and calls.starts == 0
    assert policy.last_known_stream_status is None
    policy.set_mode("always_on")
    await eventually(lambda: calls.starts == 1)
    policy.disconnect()
    await eventually(lambda: not runtime.bot_active)
    await asyncio.sleep(0.04)
    assert policy.mode == "manual" and calls.starts == 1


async def test_coalesces_mode_changes_while_stopping_and_prevents_concurrent_starts(rig):
    policy, runtime, calls, _, _ = rig
    policy.connect()
    await eventually(lambda: calls.starts == 1)
    calls.stop_gate = asyncio.Event()
    policy.disconnect()
    await eventually(lambda: policy.pending)
    await asyncio.sleep(0.005)
    policy.set_mode("always_on")
    policy.set_mode("disabled")
    policy.set_mode("always_on")
    assert policy.pending and calls.active == 1
    calls.stop_gate.set()
    await eventually(lambda: calls.starts == 2 and not policy.pending)
    assert runtime.bot_active and calls.maximum == 1


@pytest.mark.parametrize("state_name", ["connecting", "reconnecting", "connected"])
async def test_disabling_any_active_connection_state_stays_disconnected(rig, state_name):
    policy, runtime, calls, state, _ = rig
    policy.connect()
    await eventually(lambda: calls.starts == 1)
    state.set_twitch_connection_state(state_name)
    policy.set_mode("disabled")
    await eventually(lambda: not runtime.bot_active)
    await asyncio.sleep(0.03)
    assert calls.starts == 1 and state.twitch_connection_state == "stopped"


async def test_persistence_failure_leaves_applied_policy_and_twitch_intact(rig, monkeypatch):
    policy, runtime, calls, _, store = rig
    policy.connect()
    await eventually(lambda: calls.starts == 1)
    before = store._path.read_bytes()
    def fail(*args, **kwargs):
        raise OSError("private-path")
    monkeypatch.setattr("app.app_settings.os.replace", fail)
    with pytest.raises(OSError):
        policy.set_mode("disabled")
    assert policy.mode == "manual" and policy.desired_running and runtime.bot_active
    assert store._path.read_bytes() == before


async def test_shutdown_cancels_inflight_monitor_without_late_connection(rig):
    policy, runtime, calls, _, _ = rig
    calls.gate, calls.live = asyncio.Event(), True
    policy.set_mode("stream_only")
    await eventually(lambda: calls.polls == 1)
    await policy.close()
    calls.gate.set()
    await asyncio.sleep(0)
    assert policy._monitor.done() and policy._worker.done()
    assert calls.starts == 0 and calls.closed
    with pytest.raises(ValueError):
        policy.set_mode("always_on")


@pytest.mark.parametrize("mode", sorted(OPERATION_MODES))
async def test_restart_uses_saved_mode_but_never_manual_run_intent(rig, mode):
    policy, runtime, calls, _, store = rig
    policy.set_mode(mode)
    if mode == "manual":
        policy.connect()
        await eventually(lambda: calls.starts == 1)
    restored = OperationPolicy(runtime, AppSettingsStore(store._path))
    assert restored.mode == mode
    assert restored.desired_running == (mode == "always_on")


def test_operation_mode_preserved_by_desktop_ai_updates_and_invalid_settings(tmp_path):
    path = tmp_path / "app_settings.json"
    store = AppSettingsStore(path)
    assert store.snapshot().startup.operation_mode == "always_on"  # Existing profiles.
    store.update_operation_mode("disabled")
    store.update_desktop(start_minimized=False, minimize_to_tray=False, close_to_tray=False, auto_start_bot=True)
    store.update_ai_memory(enabled=False)
    assert AppSettingsStore(path).snapshot().startup.operation_mode == "disabled"
    assert store.snapshot().startup.auto_start_bot
    for mode in (None, [], "ALWAYS_ON", True, "../../secret"):
        with pytest.raises(ValueError):
            store.update_operation_mode(mode)
    path.write_text('{"version":1,"startup":{"operation_mode":"future_mode"}}')
    assert AppSettingsStore(path).snapshot().startup.operation_mode == "disabled"
    path.write_text('{"version":1,"startup":null}')
    assert AppSettingsStore(path).snapshot().startup.operation_mode == "disabled"


@pytest.mark.parametrize("mode", ["always_on", "manual"])
@pytest.mark.parametrize("custom", [False, True])
async def test_restricted_commands_reuse_monitor_without_controlling_connection(rig, mode, custom, tmp_path):
    policy, runtime, calls, state, _ = rig
    registry = CommandRegistry()

    @registry.command("restricted")
    async def restricted(context, arguments):
        await context.reply("restricted")

    @registry.command("ordinary")
    async def ordinary(context, arguments):
        await context.reply("ordinary")

    state.configure_commands(registry.definitions())
    store = CustomCommandStore(tmp_path / "custom.json", {"restricted", "ordinary"})
    runtime.application.custom_commands = store
    if custom:
        store.save({"name": "custom", "enabled": True, "responses": ["restricted"],
            "permission": "USER", "per_user_seconds": 0, "global_seconds": 0,
            "aliases": ["alias"], "stream_availability": "live_only"})
        invocation = "!alias"
    else:
        state.apply_command_settings("restricted", stream_availability="live_only")
        invocation = "!restricted"
    policy.set_mode(mode)
    if mode == "manual":
        policy.connect()
    policy.refresh_command_monitoring()
    await eventually(lambda: calls.starts == 1 and policy.confirmed_stream_status() == "offline")
    monitor = policy._monitor
    replies = []

    async def respond(text):
        replies.append(text)

    dispatcher = CommandDispatcher(registry, CooldownManager(), logging.getLogger(__name__), "!",
                                   runtime_state=state, custom_commands=store)
    async def send(content):
        await dispatcher.dispatch(IncomingChatMessage("channel", content, ChatAuthor("300", "viewer"), respond),
                                  runtime.application.services)

    await send(invocation)
    await send("!ordinary")
    assert replies == ["ordinary"]
    calls.live = True
    await eventually(lambda: policy.confirmed_stream_status() == "live")
    await send(invocation)
    assert replies[-1] == "restricted"
    calls.live = OSError("synthetic API failure")
    await eventually(lambda: policy.confirmed_stream_status() == "unknown")
    await send(invocation)
    await send("!ordinary")
    assert replies == ["ordinary", "restricted", "ordinary"]
    calls.live = False
    await eventually(lambda: policy.confirmed_stream_status() == "offline")
    assert runtime.bot_active and calls.starts == 1 and policy.desired_running
    assert policy._monitor is monitor and calls.maximum == 1
    # Repeated ordinary editor writes must not bypass polling/backoff.
    before = calls.polls
    for _ in range(20):
        policy.refresh_command_monitoring()
    assert calls.polls == before
    assert not policy._monitor_wake.is_set()


@pytest.mark.parametrize("live", [False, True])
async def test_confirmation_expires_and_failure_never_authorizes_offline(rig, live):
    policy, _, calls, state, _ = rig
    now = [0.0]
    policy._clock = lambda: now[0]
    calls.live = live
    policy.set_mode("stream_only")
    await eventually(lambda: policy.confirmed_stream_status() == ("live" if live else "offline"))
    assert state.command_stream_available("live_only" if live else "offline_only")
    now[0] = 2 * policy._poll_interval + policy._request_timeout
    assert policy.confirmed_stream_status() == "unknown"
    assert policy.snapshot()["stream_status"] == "unknown"
    assert not state.command_stream_available("offline_only")
    assert not state.command_stream_available("live_only")
    assert state.command_stream_available("anytime")
    calls.live = OSError("synthetic")
    await eventually(lambda: policy.stream_status == "unknown")
    assert not state.command_stream_available("offline_only")


async def test_monitor_timeout_is_unknown_and_preserves_anytime_and_connection(rig):
    policy, runtime, calls, state, _ = rig
    policy.set_mode("stream_only")
    calls.live = True
    await eventually(lambda: calls.starts == 1)
    calls.gate = asyncio.Event()
    await eventually(lambda: policy.stream_status == "unknown")
    assert runtime.bot_active and policy.desired_running
    assert not state.command_stream_available("live_only")
    assert not state.command_stream_available("offline_only")
    assert state.command_stream_available("anytime")


async def test_no_api_requests_for_unrestricted_commands_or_stopped_manual(rig):
    policy, runtime, calls, state, _ = rig
    policy.set_mode("always_on")
    await eventually(lambda: runtime.bot_active)
    await asyncio.sleep(0.03)
    assert calls.polls == 0
    registry = CommandRegistry()
    @registry.command("command")
    async def command(context, arguments):
        pass
    state.configure_commands(registry.definitions())
    state.apply_command_settings("command", stream_availability="live_only")
    policy.refresh_command_monitoring()
    await eventually(lambda: calls.polls > 0)
    policy.disconnect()
    await eventually(lambda: not runtime.bot_active)
    before = calls.polls
    await asyncio.sleep(0.04)
    assert calls.polls == before and policy.confirmed_stream_status() == "unknown"
    policy.set_mode("disabled")
    await asyncio.sleep(0.03)
    assert calls.polls == before
