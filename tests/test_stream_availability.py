"""Server command restrictions at the shared dispatch and persistence boundaries."""

import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.commands.ai import register_ai_commands
from app.commands.info import register_info_commands
from app.commands.registry import CommandDispatcher, CommandRegistry
from app.custom_commands import CustomCommandStore
from app.management import ApplicationManagement
from app.runtime_state import RuntimeState
from app.services.ai_request_policy import PolicyDecision
from app.twitch.events import ChatAuthor, IncomingChatMessage
from app.twitch.permissions import Permission
from app.utils.cooldown import CooldownManager, CooldownPolicy


@pytest.fixture
def rig(tmp_path):
    registry = CommandRegistry()
    register_info_commands(registry)
    register_ai_commands(registry)
    external = AsyncMock()

    @registry.command("crosshair", aliases=("cross",), cooldown=CooldownPolicy(global_seconds=30))
    async def command(context, arguments):
        await external(arguments)
        await context.reply("crosshair")

    state = RuntimeState(command_settings_path=tmp_path / "commands.json")
    state.configure_commands(registry.definitions())
    custom = CustomCommandStore(tmp_path / "custom.json", state.reserved_command_names(),
                                namespace_lock=state.command_namespace_lock)
    state.bind_custom_commands(custom)
    saved = custom.save({"name": "hello", "enabled": True, "responses": ["hello"],
        "permission": "USER", "per_user_seconds": 0, "global_seconds": 30, "aliases": ["hi"]})
    services = SimpleNamespace(runtime_state=state, custom_commands=custom,
        settings=SimpleNamespace(twitch_bot_user_id="100", command_prefix="!"),
        ai=SimpleNamespace(is_available=True, generate_reply=AsyncMock(return_value=SimpleNamespace(is_available=True, text="AI reply"))),
        ai_request_policy=SimpleNamespace(check=Mock(return_value=PolicyDecision.ALLOW)),
        twitch=SimpleNamespace(get_current_category=AsyncMock(return_value=None)))
    application = SimpleNamespace(services=services, registry=registry, custom_commands=custom,
                                  settings=services.settings)
    management = ApplicationManagement(application, None)
    dispatcher = CommandDispatcher(registry, CooldownManager(), logging.getLogger(__name__), "!",
                                    runtime_state=state, custom_commands=custom)
    replies = []

    async def respond(content):
        replies.append(content)

    def message(content, moderator=False):
        return IncomingChatMessage("channel", content, ChatAuthor("200", "viewer", is_moderator=moderator), respond)

    return SimpleNamespace(state=state, custom=custom, saved=saved, services=services, registry=registry,
        dispatcher=dispatcher, management=management, message=message, replies=replies, external=external)


@pytest.mark.parametrize("server", [False, True], ids=["desktop", "server"])
@pytest.mark.parametrize("status", ["live", "offline", "unknown"])
@pytest.mark.parametrize("availability", ["anytime", "live_only", "offline_only"])
@pytest.mark.parametrize("custom", [False, True], ids=["builtin", "custom"])
async def test_dispatch_modes_aliases_and_desktop_isolation(rig, server, status, availability, custom):
    rig.state.server_runtime = server
    rig.state.server_stream_status = lambda: status
    if custom:
        rig.custom.save({**rig.saved.to_json(), "stream_availability": availability})
    else:
        rig.state.apply_command_settings("crosshair", stream_availability=availability)
    assert await rig.dispatcher.dispatch(rig.message("!hi" if custom else "!cross"), rig.services)
    expected = not server or availability == "anytime" or (availability == "live_only" and status == "live") or (availability == "offline_only" and status == "offline")
    assert rig.replies == (["hello" if custom else "crosshair"] if expected else [])


@pytest.mark.parametrize("custom", [False, True])
async def test_suppression_preserves_cooldown_and_permissions(rig, custom, caplog):
    caplog.set_level(logging.INFO, logger=__name__)
    rig.state.server_runtime = True
    rig.state.server_stream_status = lambda: "offline"
    if custom:
        rig.custom.save({**rig.saved.to_json(), "stream_availability": "live_only", "permission": "MODERATOR"})
    else:
        rig.state.apply_command_settings("crosshair", stream_availability="live_only", permission=Permission.MODERATOR)
    name, alias = ("hello", "hi") if custom else ("crosshair", "cross")
    await rig.dispatcher.dispatch(rig.message(f"!{alias}", True), rig.services)
    rig.state.server_stream_status = lambda: "live"
    await rig.dispatcher.dispatch(rig.message(f"!{name}"), rig.services)  # Permissions still apply.
    assert rig.replies == []
    await rig.dispatcher.dispatch(rig.message(f"!{alias}", True), rig.services)
    await rig.dispatcher.dispatch(rig.message(f"!{name}", True), rig.services)
    assert len(rig.replies) == 1  # Parent and alias share their original cooldown.
    outcomes = [record.event_outcome for record in caplog.records
                if getattr(record, "event_kind", None) in ("command.outcome", "command.cooldown")]
    assert outcomes == ["availability", "permissions", "cooldown"]


@pytest.mark.parametrize("status", ["offline", "unknown"])
async def test_ask_cannot_start_ai_memory_category_or_precheck_when_restricted(rig, status):
    rig.state.server_runtime = True
    rig.state.server_stream_status = lambda: status
    rig.state.apply_command_settings("ask", stream_availability="live_only")
    rig.services.memory = SimpleNamespace(get_recent=AsyncMock(), save_exchange=AsyncMock())
    await rig.dispatcher.dispatch(rig.message("!ask question"), rig.services)
    rig.services.ai.generate_reply.assert_not_awaited()
    rig.services.twitch.get_current_category.assert_not_awaited()
    rig.services.memory.get_recent.assert_not_awaited()
    rig.services.ai_request_policy.check.assert_not_called()
    assert rig.replies == []
    rig.state.server_stream_status = lambda: "live"
    await rig.dispatcher.dispatch(rig.message("!ask question"), rig.services)
    rig.services.ai.generate_reply.assert_awaited_once()


@pytest.mark.parametrize("status", ["live", "offline", "unknown"])
async def test_commands_visibility_respects_confirmed_state_and_public_rules(rig, status):
    rig.state.server_runtime = True
    rig.state.server_stream_status = lambda: status
    rig.state.apply_command_settings("crosshair", stream_availability="live_only")
    rig.custom.save({**rig.saved.to_json(), "stream_availability": "offline_only"})
    rig.state.apply_command_settings("ask", enabled=False)
    await rig.dispatcher.dispatch(rig.message("!commands", True), rig.services)
    text = " ".join(rig.replies)
    assert ("!crosshair" in text) == (status != "offline")
    assert "!cross " not in text
    assert ("!hello" in text) == (status != "live")
    assert "!hi " not in text
    assert "!ask" not in text and "!erase" not in text


def test_save_apply_reset_restore_restart_and_desktop_editor_isolation(rig):
    assert rig.state.get_command_settings("ask").stream_availability == "anytime"
    assert rig.saved.stream_availability == "anytime"
    assert "stream_availability" not in rig.management.get_commands()["commands"][0]
    assert "stream_availability" not in rig.management.get_custom_commands()["commands"][0]
    assert not rig.management.save_command_settings("ask", True, 0, 0, "USER", {"stream_availability": "live_only"})["ok"]
    assert not rig.management.save_custom_command({**rig.saved.to_json(), "stream_availability": "live_only"})["ok"]
    rig.state.server_runtime = True
    assert rig.management.apply_command_settings("ask", True, 0, 0, "USER", {"stream_availability": "live_only"})["ok"]
    assert not rig.state.command_settings_are_saved("ask")
    assert rig.management.save_command_settings("ask", True, 0, 0, "USER", {"stream_availability": "live_only"})["ok"]
    state = RuntimeState(command_settings_path=rig.state._command_settings_path)
    state.configure_commands(rig.registry.definitions())
    assert state.get_command_settings("ask").stream_availability == "live_only"
    assert state.command_settings_are_saved("ask")
    rig.state.remove_builtin_command("ask")
    assert rig.state.get_command_settings("ask").stream_availability == "live_only"
    assert rig.management.restore_builtin_command("ask")["ok"]
    assert rig.state.get_command_settings("ask").stream_availability == "anytime"
    assert rig.management.save_custom_command({**rig.saved.to_json(), "stream_availability": "offline_only"})["ok"]
    # An ordinary Desktop edit does not know or erase the stored Server field.
    rig.state.server_runtime = False
    assert rig.management.save_custom_command({**rig.saved.to_json(), "responses": ["edited"]})["ok"]
    restored = CustomCommandStore(rig.custom._path, rig.state.reserved_command_names())
    assert restored.get_by_name("hi").stream_availability == "offline_only"
    rig.custom.delete(rig.saved.id)
    assert not CustomCommandStore(rig.custom._path, rig.state.reserved_command_names()).list()


@pytest.mark.parametrize("invalid", [None, [], True, "Live only", "invalid"])
def test_invalid_management_values_do_not_mutate_settings(rig, invalid):
    rig.state.server_runtime = True
    before = rig.state.get_command_settings("ask")
    assert not rig.management.save_command_settings("ask", True, 0, 0, "USER", {"stream_availability": invalid})["ok"]
    assert rig.state.get_command_settings("ask") == before
    assert not rig.management.save_custom_command({**rig.saved.to_json(), "stream_availability": invalid})["ok"]
    assert rig.custom.get_by_name("hello") == rig.saved


def test_invalid_persisted_builtin_and_custom_values_are_safe(rig):
    rig.state._command_settings_path.write_text(json.dumps({"ask": {"stream_availability": "future"}}))
    state = RuntimeState(command_settings_path=rig.state._command_settings_path)
    state.configure_commands(rig.registry.definitions())
    assert state.get_command_settings("ask").stream_availability == "anytime"
    rig.custom._path.write_text(json.dumps({"version": 2, "commands": [{**rig.saved.to_json(), "stream_availability": "future"}]}))
    assert not CustomCommandStore(rig.custom._path, rig.state.reserved_command_names()).list()
