"""Factory overrides retain handlers, enforce policy and coexist with custom data."""

import json
import logging
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.commands.ai import register_ai_commands
from app.commands.fun import register_fun_commands
from app.commands.info import register_info_commands, register_weather_commands
from app.commands.registry import CommandDispatcher, CommandRegistry
from app.custom_commands import CustomCommandStore
from app.fun_settings import FATES, FunSettingsStore
from app.runtime_state import RuntimeState
from app.services.ai_request_policy import AIRequestPolicy
from app.services.contracts import AIReply, WeatherReport
from app.twitch.events import ChatAuthor, IncomingChatMessage
from app.twitch.permissions import Permission
from app.utils.cooldown import CooldownManager, CooldownPolicy
from app.utils.output_limiter import OutputLimiter
from app.webview_host import WebUIBridge


def custom_payload(**changes):
    return {"name": "promo", "enabled": True, "responses": ["Hello {sender}"],
            "permission": "USER", "per_user_seconds": 0, "global_seconds": 0,
            "aliases": [], **changes}


@pytest.mark.parametrize("field", ["primary_name", "aliases"])
def test_privacy_name_is_reserved_for_builtin_and_custom_edits(tmp_path, field):
    _, state, custom, _, _, _, _ = setup_commands(tmp_path)
    value = "optout" if field == "primary_name" else ["optout"]
    with pytest.raises(ValueError, match="already exists"):
        state.apply_command_settings("ping", **{field: value})
    with pytest.raises(ValueError, match="already exists"):
        custom.save(custom_payload(**({"name": "optout"} if field == "primary_name" else {"aliases": ["optout"]})))


def setup_commands(root):
    registry = CommandRegistry()
    fun = FunSettingsStore(root / "fun_settings.json")
    register_fun_commands(registry, fun)
    register_info_commands(registry)
    register_weather_commands(registry)
    register_ai_commands(registry)
    state = RuntimeState(command_settings_path=root / "command_settings.json")
    state.configure_commands(registry.definitions())
    factory_names = {name for definition in registry.definitions() for name in (definition.name, *definition.aliases)}
    custom = CustomCommandStore(root / "custom_commands.json", factory_names,
                                namespace_lock=state.command_namespace_lock)
    state.bind_custom_commands(custom)
    services = SimpleNamespace(runtime_state=state, ai_request_policy=AIRequestPolicy(),
        ai=SimpleNamespace(is_available=True, generate_reply=AsyncMock(return_value=AIReply("An actual answer", True))),
        users=SimpleNamespace(get_by_username=AsyncMock(return_value=SimpleNamespace(twitch_user_id="target-id"))),
        weather=SimpleNamespace(get_current_weather=AsyncMock(return_value=WeatherReport("London", 15, "Clear", 4))),
        memory=None, custom_commands=custom, settings=SimpleNamespace(command_prefix="!"))
    application = SimpleNamespace(registry=registry, services=services, fun_settings=fun, custom_commands=custom,
                                  settings=SimpleNamespace(command_prefix="!"))
    bridge = WebUIBridge(SimpleNamespace(application=application))
    dispatcher = CommandDispatcher(registry, CooldownManager(), logging.getLogger(__name__), "!",
                                    runtime_state=state, custom_commands=custom)
    return registry, state, custom, fun, bridge, dispatcher, services


def chat(content, respond, **roles):
    return IncomingChatMessage("test", content, ChatAuthor("user", "caller", **roles), respond, channel_id="100")


@pytest.mark.asyncio
async def test_command_help_tracks_custom_edits_builtin_aliases_removal_and_restart(tmp_path):
    registry, state, custom, _, bridge, dispatcher, services = setup_commands(tmp_path)
    for name in ("commands", "help"):
        state.apply_command_settings(name, cooldown=CooldownPolicy())
    state.apply_command_settings("commands", primary_name="catalog", aliases=["commands"])
    state.apply_command_settings("help", primary_name="guide", aliases=["help"])

    async def listing():
        response = AsyncMock()
        await dispatcher.dispatch(chat("!commands", response, is_moderator=True), services)
        response.assert_awaited_once()
        services.ai.generate_reply.assert_not_awaited()
        return response.await_args.args[0]

    initial = await listing()
    assert "!ask <question>" in initial
    assert "!erase" not in initial
    command = custom.save(custom_payload(aliases=["offer"]))
    added = await listing()
    assert "!promo" in added and "!offer" not in added
    assert added.count("!promo") == 1
    command = custom.save({**command.to_json(), "name": "news", "aliases": ["updates"]})
    renamed = await listing()
    assert "!news" in renamed and "!updates" not in renamed
    assert "!promo" not in renamed and "!offer" not in renamed
    command = custom.save({**command.to_json(), "enabled": False})
    assert "!news" not in await listing()
    command = custom.save({**command.to_json(), "enabled": True})
    assert "!news" in await listing()

    state.apply_command_settings("weather", aliases=["forecast"], display_name="Weather in UI")
    applied = await listing()
    assert "!weather <city>" in applied and "!forecast" not in applied
    assert "Weather in UI" not in applied  # UI labels do not rename chat commands.
    state.apply_command_settings("weather", aliases=["conditions"])
    assert "!forecast" not in await listing()
    state.save_command_override("weather")
    state.apply_command_settings("tg", burst_max_count=7)
    assert "!tg [1-7]" in await listing()
    state.apply_command_settings("ping", enabled=False)
    assert "!ping" not in await listing()
    state.save_command_override("ping")
    bridge.remove_builtin_command("weather")
    removed = await listing()
    assert "!weather" not in removed and "!conditions" not in removed

    restarted = setup_commands(tmp_path)
    saved_entries = restarted[0].help_entries(restarted[1], restarted[2])
    assert "!news" in saved_entries and "!updates" not in saved_entries
    assert not any(entry.startswith(("!weather", "!conditions", "!ping")) for entry in saved_entries)
    assert bridge.restore_builtin_command("weather") == {"ok": True}
    restored = await listing()
    assert "!weather <city>" in restored and "!conditions" not in restored
    custom.delete(command.id)
    assert "!news" not in await listing() and "!updates" not in await listing()
    restarted = setup_commands(tmp_path)
    assert "!news" not in restarted[0].help_entries(restarted[1], restarted[2])


@pytest.mark.asyncio
async def test_command_help_pages_preserve_utf8_limits_permissions_and_output_limiter(tmp_path):
    registry, state, custom, _, _, _, services = setup_commands(tmp_path)
    services.settings.command_prefix = "?"
    for name in ("commands", "help"):
        state.apply_command_settings(name, cooldown=CooldownPolicy())
    state.apply_command_settings("commands", primary_name="catalog", aliases=["commands"])
    state.apply_command_settings("help", primary_name="guide", aliases=["help"])
    for index in range(12):
        custom.save(custom_payload(name=f"{index}雪" + "😀" * 35, aliases=[f"alias{index}"]))
    expected = registry.help_entries(state, custom, "?")
    limiter = OutputLimiter(interval=0)
    dispatcher = CommandDispatcher(registry, CooldownManager(), logging.getLogger(__name__), "?",
                                   runtime_state=state, custom_commands=custom, output_limiter=limiter)
    response = AsyncMock()
    await dispatcher.dispatch(chat("?commands", response), services)
    response.assert_not_awaited()  # Listing does not lower moderator permission.
    observed = []
    page = 1
    while True:
        response.reset_mock()
        await dispatcher.dispatch(chat(f"?commands {page}", response, is_moderator=True), services)
        text = response.await_args.args[0]
        assert len(text.encode("utf-8")) <= 450
        assert text.startswith(f"Commands ({page}/")
        body = text.split(": ", 1)[1].split(" | Next:", 1)[0]
        observed.extend(part.split(" ", 1)[0] for part in body.split("?")[1:])
        if " | Next:" not in text:
            break
        assert text.endswith(f"?catalog {page + 1}")
        page += 1
        assert page <= len(expected)
    assert page > 1
    assert observed == [entry.split(" ", 1)[0][1:] for entry in expected]
    assert expected[-1] == "?optout - Don't save my data"
    assert observed.count("optout") == 1 and observed[-1] == "optout"
    response.reset_mock()
    await dispatcher.dispatch(chat("?commands nonsense", response, is_moderator=True), services)
    assert response.await_args.args[0] == "Usage: ?catalog [page]"
    response.reset_mock()
    await dispatcher.dispatch(chat("?guide nonsense", response), services)
    assert response.await_args.args[0] == "Usage: ?guide [page]"

    # Public !help uses the same entries; ordinary help requests still acquire
    # the shared limiter per message rather than bypassing it with a burst.
    dispatcher._output_limiter = OutputLimiter(interval=5)
    response.reset_mock()
    await dispatcher.dispatch(chat("?help", response), services)
    await dispatcher.dispatch(chat("?help 2", response), services)
    assert response.await_count == 1


@pytest.mark.parametrize("arguments", ["0", "-1", "2", "nope", "1 2", "9" * 500])
def test_command_help_rejects_invalid_or_out_of_range_pages(arguments):
    from app.commands.info import command_help_page

    reply = command_help_page(("!ask <question>",), "!commands", arguments)
    assert reply.startswith(("Usage:", "Choose a page"))
    assert len(reply.encode("utf-8")) <= 450


@pytest.mark.asyncio
async def test_editor_aliases_dispatch_original_handler_and_share_cooldown(tmp_path):
    registry, state, custom, _, bridge, dispatcher, services = setup_commands(tmp_path)
    original = registry.get("ping")
    custom.save(custom_payload())
    assert bridge.save_command_settings("ping", True, 30, 0, "MODERATOR",
        {"aliases": ["!PONG"], "display_name": "Connection check"}) == {"ok": True}
    assert state.get_command_settings("ping").aliases == ("pong",)
    respond = AsyncMock()
    await dispatcher.dispatch(chat("!pong", respond, is_moderator=True), services)
    await dispatcher.dispatch(chat("!ping", respond, is_moderator=True), services)
    assert respond.await_args_list[0].args == ("pong",)
    assert respond.await_count == 1
    assert registry.get("ping") is original
    restarted = setup_commands(tmp_path)
    assert restarted[1].get_command_settings("ping") == state.get_command_settings("ping")
    assert restarted[2].list() == custom.list()
    entry = next(command for command in bridge.get_commands()["commands"] if command["name"] == "ping")
    assert entry["name"] == "ping" and entry["display_name"] == "Connection check"
    assert entry["response_pool"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("server", [False, True], ids=["desktop", "server"])
async def test_primary_rename_preserves_id_handler_cooldown_aliases_and_saved_state(tmp_path, server):
    registry, state, custom, _, bridge, dispatcher, services = setup_commands(tmp_path)
    state.server_runtime = server
    original = registry.get("ping")
    assert bridge.save_command_settings("ping", True, 30, 0, "MODERATOR",
        {"primary_name": "!CHECK", "aliases": ["pong"], "display_name": "Connection"})["ok"]
    metadata = next(item for item in bridge.get_commands()["commands"] if item["name"] == "ping")
    assert metadata["primary_name"] == "check"
    assert metadata["help_text"] == "!check"
    assert metadata["default_settings"]["primary_name"] == "ping"
    response = AsyncMock()
    assert not await dispatcher.dispatch(chat("!ping", response, is_moderator=True), services)
    await dispatcher.dispatch(chat("!check", response), services)
    response.assert_not_awaited()
    await dispatcher.dispatch(chat("!check", response, is_moderator=True), services)
    await dispatcher.dispatch(chat("!pong", response, is_moderator=True), services)
    assert response.await_count == 1
    # Another rename cannot reset the same stable command's cooldown.
    state.apply_command_settings("ping", primary_name="verify", aliases=["ping", "pong"])
    await dispatcher.dispatch(chat("!verify", response, is_moderator=True), services)
    await dispatcher.dispatch(chat("!ping", response, is_moderator=True), services)
    assert response.await_count == 1
    assert registry.get("ping") is original
    assert state.resolve_command_alias("ping") == "ping"
    entries = registry.help_entries(state, custom)
    assert "!verify" in entries and "!check" not in entries and "!pong" not in entries and "!ping" not in entries
    assert setup_commands(tmp_path)[1].get_command_settings("ping").primary_name == "check"
    assert bridge.reset_command_settings("ping")["ok"]
    assert state.get_command_settings("ping") == original.default_settings
    assert setup_commands(tmp_path)[1].get_command_settings("ping").primary_name == "ping"


@pytest.mark.parametrize("name", ["", "   ", "two words", "bad{name}", "x" * 41, 123, None,
    "TG", "ERASE", "weather", "PROMO", "HI", "otheralias", "savedname", "savedalias", "ownalias"])
def test_primary_namespace_validation_is_atomic_for_apply_and_save(tmp_path, name):
    _, state, custom, _, bridge, _, _ = setup_commands(tmp_path)
    custom.save(custom_payload(aliases=["hi"]))
    assert bridge.save_command_settings("weather", True, 0, 0, "USER",
        {"primary_name": "savedname", "aliases": ["savedalias"]})["ok"]
    state.apply_command_settings("weather", primary_name="conditions", aliases=["otheralias"])
    assert bridge.save_command_settings("ping", True, 5, 7, "MODERATOR", {"aliases": ["ownalias"]})["ok"]
    before = state.get_command_settings("ping")
    path = tmp_path / "command_settings.json"
    saved = path.read_bytes()
    for action in (bridge.apply_command_settings, bridge.save_command_settings):
        assert not action("ping", False, 9, 10, "VIP", {"primary_name": name})["ok"]
        assert state.get_command_settings("ping") == before
        assert path.read_bytes() == saved


def test_custom_collisions_and_factory_restoration_reserve_saved_and_runtime_primary_names(tmp_path):
    _, state, custom, fun, bridge, _, _ = setup_commands(tmp_path)
    custom.save(custom_payload())
    assert bridge.save_command_settings("tg", True, 2, 5, "MODERATOR", {"primary_name": "community"})["ok"]
    state.apply_command_settings("tg", primary_name="sessioncommunity")
    for name in ("COMMUNITY", "sessioncommunity", "tg"):
        with pytest.raises(ValueError, match="already exists"):
            custom.save(custom_payload(name=name))
    bridge.remove_builtin_command("tg")
    assert bridge.restore_builtin_command("tg")["ok"]
    assert state.get_command_settings("tg").primary_name == "tg"
    assert custom.save(custom_payload(name="community"))
    bridge.save_command_settings("fate", True, 0, 0, "USER", {"primary_name": "destiny"})
    assert bridge.reset_all_builtin_commands()["ok"]
    assert state.get_command_settings("fate").primary_name == "fate"
    assert len(custom.list()) == 2
    assert fun.tg_message


def test_failed_primary_save_and_startup_conflict_preserve_file_and_other_settings(tmp_path, monkeypatch):
    _, state, custom, _, bridge, _, _ = setup_commands(tmp_path)
    custom.save(custom_payload(name="conditions"))
    path = tmp_path / "command_settings.json"
    original = b'{"weather":{"primary_name":"conditions","aliases":["climate"],"permission":"VIP"}}'
    path.write_bytes(original)
    restarted = setup_commands(tmp_path)[1]
    assert restarted.get_command_settings("weather").primary_name == "weather"
    assert restarted.get_command_settings("weather").aliases == ("climate",)
    assert restarted.get_command_settings("weather").permission == Permission.VIP
    assert path.read_bytes() == original
    before = state.get_command_settings("weather")
    def fail(*args, **kwargs):
        raise OSError("Synthetic write failure")
    monkeypatch.setattr("app.runtime_state.save_command_overrides", fail)
    assert not bridge.save_command_settings("weather", True, 0, 0, "USER", {"primary_name": "climate"})["ok"]
    assert state.get_command_settings("weather") == before
    assert path.read_bytes() == original


@pytest.mark.asyncio
async def test_renamed_ai_and_hidden_admin_keep_privacy_and_authority(tmp_path):
    registry, state, custom, _, bridge, dispatcher, services = setup_commands(tmp_path)
    assert bridge.save_command_settings("ask", True, 0, 0, "USER",
        {"primary_name": "question", "aliases": ["ask"]})["ok"]
    assert bridge.save_command_settings("erase", True, 0, 0, "BROADCASTER",
        {"primary_name": "forget", "aliases": ["erase"]})["ok"]
    services.ai_user_blocks = SimpleNamespace(is_blocked=lambda *_: True, remember_observed_id=lambda *_: None)
    response = AsyncMock()
    for trigger in ("question", "ask"):
        message = chat(f"!{trigger} Private question", response)
        assert dispatcher.is_ai_command(message)
        assert dispatcher.is_ai_request_blocked(message, services)
        await dispatcher.dispatch(message, services)
    services.ai.generate_reply.assert_not_awaited()
    response.assert_not_awaited()
    services.memory = SimpleNamespace(erase_for_user=AsyncMock())
    await dispatcher.dispatch(chat("!forget @target", response, is_moderator=True), services)
    services.memory.erase_for_user.assert_not_awaited()
    await dispatcher.dispatch(chat("!forget @target", response, is_broadcaster=True), services)
    services.memory.erase_for_user.assert_awaited_once_with("target-id", channel_id="100")
    assert "!question <question>" in registry.help_entries(state, custom)
    assert not any(entry.startswith(("!forget", "!erase", "!ask")) for entry in registry.help_entries(state, custom))


@pytest.mark.asyncio
@pytest.mark.parametrize("command,arguments,usage,permission", [
    ("weather", "", " <city>", "USER"), ("fate", "extra", "", "USER"),
    ("tg", "bad", " [1-10] (default: 1)", "MODERATOR"), ("uptime", "extra", "", "MODERATOR")])
async def test_renamed_usage_uses_current_primary_even_when_invoked_by_alias(tmp_path, command, arguments, usage, permission):
    _, _, _, _, bridge, dispatcher, services = setup_commands(tmp_path)
    services.settings.command_prefix = "?"
    dispatcher._command_prefix = "?"
    assert bridge.save_command_settings(command, True, 0, 0, permission,
        {"primary_name": "renamed", "aliases": [command]})["ok"]
    response = AsyncMock()
    await dispatcher.dispatch(chat(f"?{command} {arguments}", response, is_moderator=True), services)
    assert response.await_args.args[0] == f"Usage: ?renamed{usage}"


@pytest.mark.asyncio
async def test_remove_disables_canonical_and_alias_help_then_restore_factory_settings(tmp_path):
    registry, state, _, fun, bridge, dispatcher, services = setup_commands(tmp_path)
    fun.save(["My community"], "tg")
    original = registry.get("tg")
    bridge.save_command_settings("tg", True, 0, 0, "MODERATOR", {"aliases": ["community"], "burst_interval_ms": 200})
    assert bridge.remove_builtin_command("tg") == {"ok": True}
    assert state.get_command_settings("tg").removed
    assert not state.get_command_settings("tg").enabled
    respond = AsyncMock()
    for invocation in ("!tg 2", "!community 2"):
        await dispatcher.dispatch(chat(invocation, respond, is_moderator=True), services)
    respond.assert_not_awaited()
    assert not any(entry.startswith("!tg") for entry in registry.help_entries(state))
    await dispatcher.dispatch(chat("!help", respond), services)
    assert "!tg" not in respond.await_args.args[0]
    restarted = setup_commands(tmp_path)
    assert restarted[1].get_command_settings("tg").removed
    # A generic enable toggle cannot revive a removed factory command.
    state.apply_command_settings("tg", enabled=True)
    assert not state.is_command_enabled("tg")
    assert bridge.restore_builtin_command("tg") == {"ok": True}
    assert state.get_command_settings("tg") == original.default_settings
    assert registry.get("tg") is original
    assert fun.tg_message == "My community"  # Settings restore is separate from message reset.
    respond.reset_mock()
    await dispatcher.dispatch(chat("!tg 2", respond, is_moderator=True), services)
    assert respond.await_count == 2
    assert all(call.args == ("My community",) for call in respond.await_args_list)


def test_complete_factory_reset_keeps_custom_and_unknown_response_data(tmp_path):
    registry, state, custom, fun, bridge, _, _ = setup_commands(tmp_path)
    command = custom.save(custom_payload())
    custom_before = (tmp_path / "custom_commands.json").read_bytes()
    fun.save(["custom fate"], "fate")
    fun.save(["custom community"], "tg")
    fun._payload["future_response_section"] = {"retain": True}
    bridge.save_command_settings("tg", True, 8, 10, "BROADCASTER", {"burst_interval_ms": 1000})
    bridge.remove_builtin_command("weather")
    assert bridge.reset_all_builtin_commands() == {"ok": True}
    assert all(state.get_command_settings(definition.name) == definition.default_settings
               for definition in registry.definitions())
    assert fun.fates == FATES
    assert not fun.snapshot("tg")["has_saved_override"]
    assert json.loads(fun.path.read_text())["future_response_section"] == {"retain": True}
    assert custom.list() == (command,)
    assert (tmp_path / "custom_commands.json").read_bytes() == custom_before
    assert json.loads((tmp_path / "command_settings.json").read_text()) == {}


def test_complete_restore_reports_partial_response_failure_without_false_success(tmp_path, monkeypatch):
    _, state, _, fun, bridge, _, _ = setup_commands(tmp_path)
    bridge.remove_builtin_command("tg")
    fun.save(["My community"], "tg")
    def fail_reset():
        raise OSError("Synthetic failure")
    monkeypatch.setattr(fun, "reset_all", fail_reset)
    result = bridge.reset_all_builtin_commands()
    assert result["ok"] is False
    assert "settings were restored" in result["error"]
    assert not state.get_command_settings("tg").removed
    assert fun.tg_message == "My community"


@pytest.mark.parametrize("alias", ["tg", "erase", "weather", "promo", "hi"])
def test_builtin_alias_collision_with_factory_and_custom_names_and_aliases(tmp_path, alias):
    _, state, custom, _, bridge, _, _ = setup_commands(tmp_path)
    custom.save(custom_payload(aliases=["hi"]))
    before = state.get_command_settings("ping")
    result = bridge.save_command_settings("ping", True, 0, 0, "USER", {"aliases": [alias]})
    assert result["ok"] is False
    assert state.get_command_settings("ping") == before


def test_custom_edits_reserve_runtime_and_saved_builtin_aliases_even_after_removal(tmp_path):
    _, state, custom, _, bridge, _, _ = setup_commands(tmp_path)
    bridge.save_command_settings("ping", True, 0, 0, "USER", {"aliases": ["savedping"]})
    state.apply_command_settings("ping", aliases=["sessionping"])
    for name in ("savedping", "sessionping"):
        with pytest.raises(ValueError, match="already exists"):
            custom.save(custom_payload(name=name))
    bridge.remove_builtin_command("ping")
    with pytest.raises(ValueError, match="already exists"):
        custom.save(custom_payload(name="sessionping"))
    bridge.restore_builtin_command("ping")
    assert custom.save(custom_payload(name="sessionping"))


def test_startup_conflict_keeps_existing_custom_command_and_recovers_original_override(tmp_path):
    _, _, custom, _, _, _, _ = setup_commands(tmp_path)
    command = custom.save(custom_payload(aliases=["hello"]))
    path = tmp_path / "command_settings.json"
    original = b'{"ping":{"aliases":["hello"],"display_name":"Keep this label"},"future":{"data":true}}'
    path.write_bytes(original)
    _, state, restarted_custom, _, bridge, _, _ = setup_commands(tmp_path)
    assert restarted_custom.list() == (command,)
    assert state.get_command_settings("ping").aliases == ()
    assert state.get_command_settings("ping").display_name == "Keep this label"
    assert path.read_bytes() == original
    assert bridge.save_command_settings("ping", False, 0, 0, "USER") == {"ok": True}
    assert [copy.read_bytes() for copy in tmp_path.glob("*.recovery")] == [original]
    restarted_custom.save({**command.to_json(), "enabled": False})


@pytest.mark.parametrize("name,permission", [("tg", "USER"), ("tg", "VIP"), ("erase", "MODERATOR")])
def test_privileged_permissions_rejected_at_editor_and_clamped_on_restart(tmp_path, name, permission):
    registry, state, _, _, bridge, _, _ = setup_commands(tmp_path)
    assert bridge.save_command_settings(name, True, 0, 0, permission)["ok"] is False
    path = tmp_path / "command_settings.json"
    path.write_text(json.dumps({name: {"permission": permission}}))
    restarted = setup_commands(tmp_path)
    assert restarted[1].get_command_settings(name).permission == registry.get(name).minimum_permission
    assert state.get_command_settings(name).permission >= registry.get(name).minimum_permission


@pytest.mark.parametrize("name", ["ask", "erase"])
def test_administrative_and_ai_names_keep_dynamic_templates_and_authority(tmp_path, name):
    _, _, _, _, bridge, _, _ = setup_commands(tmp_path)
    permission = "BROADCASTER" if name == "erase" else "USER"
    for options in ({"aliases": ["override"]}, {"display_name": "A static template"}):
        assert bridge.save_command_settings(name, True, 0, 0, permission, options)["ok"] is True
    assert bridge.save_command_responses(name, ["Static text"])["ok"] is False
    metadata = next(command for command in bridge.get_commands()["commands"] if command["name"] == name)
    assert metadata["identity_editable"] is True
    assert metadata["response_pool"] is None


@pytest.mark.asyncio
async def test_edited_dynamic_commands_keep_original_ask_weather_and_erase_implementations(tmp_path):
    registry, _, _, _, bridge, dispatcher, services = setup_commands(tmp_path)
    original_handlers = {definition.name: definition.handler for definition in registry.definitions()}
    bridge.save_command_settings("weather", True, 0, 0, "USER", {"aliases": ["forecastweather"], "display_name": "Local weather"})
    bridge.save_command_settings("ask", True, 0, 0, "USER")
    bridge.remove_builtin_command("erase")
    bridge.restore_builtin_command("erase")
    respond = AsyncMock()
    await dispatcher.dispatch(chat("!forecastweather London", respond), services)
    services.weather.get_current_weather.assert_awaited_once_with("London")
    assert "London" in respond.await_args.args[0]
    await dispatcher.dispatch(chat("!ask Explain plants", respond), services)
    assert services.ai.generate_reply.await_args.kwargs["prompt"] == "Explain plants"
    assert respond.await_args.args[0] == "@caller An actual answer"
    services.memory = SimpleNamespace(erase_for_user=AsyncMock())
    await dispatcher.dispatch(chat("!erase @target", respond, is_moderator=True), services)
    services.memory.erase_for_user.assert_not_awaited()
    await dispatcher.dispatch(chat("!erase @target", respond, is_broadcaster=True), services)
    services.memory.erase_for_user.assert_awaited_once_with("target-id", channel_id="100")
    assert original_handlers == {definition.name: definition.handler for definition in registry.definitions()}


@pytest.mark.parametrize("interval", [0, 50, 200, 1000])
def test_intervals_persist_across_restart_and_do_not_cross_profiles(tmp_path, interval):
    _, state, custom, _, bridge, _, _ = setup_commands(tmp_path / "first")
    assert bridge.save_command_settings("tg", True, 0, 0, "MODERATOR", {"burst_interval_ms": interval}) == {"ok": True}
    command = custom.save(custom_payload(response_mode="burst", permission="MODERATOR", burst_count=3,
                                         burst_allow_override=True, burst_interval_ms=interval))
    first = setup_commands(tmp_path / "first")
    second = setup_commands(tmp_path / "second")
    assert first[1].get_command_settings("tg").burst_interval_ms == interval
    assert first[2].list() == (command,)
    assert second[1].get_command_settings("tg").burst_interval_ms == 0
    assert second[2].list() == ()
    assert first[4].get_custom_commands()["commands"][0]["burst_interval_ms"] == interval


@pytest.mark.parametrize("interval", [-1, 1001, 1.5, True, "50", None])
def test_invalid_intervals_rejected_without_mutation_and_invalid_disk_fields_fall_back(tmp_path, interval):
    _, state, custom, _, bridge, _, _ = setup_commands(tmp_path)
    before = state.get_command_settings("tg")
    assert bridge.save_command_settings("tg", True, 0, 0, "MODERATOR", {"burst_interval_ms": interval})["ok"] is False
    assert state.get_command_settings("tg") == before
    with pytest.raises(ValueError, match="interval"):
        custom.save(custom_payload(response_mode="burst", permission="MODERATOR", burst_interval_ms=interval))
    (tmp_path / "command_settings.json").write_text(json.dumps({"tg": {"burst_interval_ms": interval}}))
    restarted = setup_commands(tmp_path)
    assert restarted[1].get_command_settings("tg").burst_interval_ms == 0


def test_old_builtin_settings_and_version_two_bursts_default_to_zero_without_rewrite(tmp_path):
    _, _, custom, _, _, _, _ = setup_commands(tmp_path)
    custom.save(custom_payload(response_mode="burst", permission="MODERATOR", burst_count=4))
    path = tmp_path / "command_settings.json"
    original = b'{"weather":{"enabled":false,"cooldown":{"global_seconds":8},"permission":"VIP"}}'
    path.write_bytes(original)
    custom_before = (tmp_path / "custom_commands.json").read_bytes()
    _, state, commands, _, _, _, _ = setup_commands(tmp_path)
    assert state.get_command_settings("weather").enabled is False
    assert state.get_command_settings("weather").permission == Permission.VIP
    assert state.get_command_settings("weather").cooldown.global_seconds == 8
    assert state.get_command_settings("tg").burst_interval_ms == 0
    assert state.get_command_settings("tg").burst_max_count == 10
    assert commands.list()[0].burst_interval_ms == 0
    assert path.read_bytes() == original
    assert (tmp_path / "custom_commands.json").read_bytes() == custom_before


@pytest.mark.parametrize("maximum", [1, 5, 20])
def test_tg_maximum_persists_in_existing_store_and_resets_independently(tmp_path, maximum):
    _, state, _, fun, bridge, _, _ = setup_commands(tmp_path)
    fun.save(["My community"], "tg")
    options = {"burst_max_count": maximum, "burst_interval_ms": 50, "aliases": ["community"]}
    assert bridge.save_command_settings("tg", True, 8, 10, "BROADCASTER", options) == {"ok": True}
    saved = state.get_command_settings("tg")
    assert saved.burst_max_count == maximum
    assert setup_commands(tmp_path)[1].get_command_settings("tg") == saved
    assert setup_commands(tmp_path / "other")[1].get_command_settings("tg").burst_max_count == 10
    entry = next(command for command in bridge.get_commands()["commands"] if command["name"] == "tg")
    assert entry["burst_max_count"] == maximum
    assert entry["default_settings"]["burst_max_count"] == 10
    # Older callers that omit the new option keep the saved maximum.
    assert bridge.save_command_settings("tg", True, 8, 10, "BROADCASTER") == {"ok": True}
    assert state.get_command_settings("tg").burst_max_count == maximum
    assert bridge.reset_command_settings("tg") == {"ok": True}
    assert state.get_command_settings("tg").burst_max_count == 10
    assert fun.tg_message == "My community"


@pytest.mark.parametrize("maximum", [0, -1, 21, 1.5, True, "5", None])
def test_invalid_tg_maximum_never_mutates_settings_or_rewrites_loaded_file(tmp_path, maximum):
    _, state, _, _, bridge, _, _ = setup_commands(tmp_path)
    assert bridge.save_command_settings("tg", True, 0, 0, "MODERATOR", {"burst_max_count": 5}) == {"ok": True}
    before = state.get_command_settings("tg")
    path = tmp_path / "command_settings.json"
    saved_bytes = path.read_bytes()
    for action in (bridge.apply_command_settings, bridge.save_command_settings):
        assert action("tg", True, 0, 0, "MODERATOR", {"burst_max_count": maximum})["ok"] is False
        assert state.get_command_settings("tg") == before
        assert path.read_bytes() == saved_bytes
    path.write_text(json.dumps({"tg": {"burst_max_count": maximum, "burst_interval_ms": 50, "enabled": False}}))
    invalid_bytes = path.read_bytes()
    restarted = setup_commands(tmp_path)[1].get_command_settings("tg")
    assert restarted.burst_max_count == 10
    assert restarted.burst_interval_ms == 50 and not restarted.enabled
    assert path.read_bytes() == invalid_bytes


def test_tg_maximum_apply_is_session_only_and_save_failure_keeps_previous_limit(tmp_path, monkeypatch):
    _, state, _, _, bridge, _, _ = setup_commands(tmp_path)
    assert bridge.apply_command_settings("tg", True, 0, 0, "MODERATOR", {"burst_max_count": 20}) == {"ok": True}
    assert state.get_command_settings("tg").burst_max_count == 20
    assert setup_commands(tmp_path)[1].get_command_settings("tg").burst_max_count == 10
    def fail_save(*args, **kwargs):
        raise OSError("Synthetic write failure")
    monkeypatch.setattr("app.runtime_state.save_command_overrides", fail_save)
    assert bridge.save_command_settings("tg", True, 0, 0, "MODERATOR", {"burst_max_count": 5})["ok"] is False
    assert state.get_command_settings("tg").burst_max_count == 20
    assert bridge.save_command_settings("ping", True, 0, 0, "MODERATOR", {"burst_max_count": 20})["ok"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("maximum,count", [(1, 1), (5, 5), (20, 20)])
async def test_tg_configured_maximum_rejects_whole_batch_before_cooldown(tmp_path, maximum, count):
    _, state, _, _, _, dispatcher, services = setup_commands(tmp_path)
    state.apply_command_settings("tg", burst_max_count=maximum, aliases=["community"],
                                 cooldown=CooldownPolicy(global_seconds=60))
    respond = AsyncMock()
    await dispatcher.dispatch(chat(f"!community {maximum + 1}", respond, is_moderator=True), services)
    # Above the absolute cap gets usage; above a smaller configured limit is silent.
    assert respond.await_count == (1 if maximum == 20 else 0)
    respond.reset_mock()
    await dispatcher.dispatch(chat(f"!tg {count}", respond, is_moderator=True), services)
    assert respond.await_count == count
    await dispatcher.dispatch(chat("!community", respond, is_moderator=True), services)
    assert respond.await_count == count  # Canonical/alias cooldowns still apply.


def test_remove_and_restore_failures_preserve_effective_and_saved_state(tmp_path, monkeypatch):
    _, state, _, _, bridge, _, _ = setup_commands(tmp_path)
    bridge.save_command_settings("ping", False, 5, 8, "USER", {"aliases": ["hello"]})
    path = tmp_path / "command_settings.json"
    before = path.read_bytes()
    current = state.get_command_settings("ping")
    def failed_write(*args, **kwargs):
        raise OSError("Synthetic atomic replacement failure")
    monkeypatch.setattr("app.runtime_state.save_command_overrides", failed_write)
    assert bridge.remove_builtin_command("ping")["ok"] is False
    assert bridge.restore_builtin_command("ping")["ok"] is False
    assert state.get_command_settings("ping") == current
    assert path.read_bytes() == before
