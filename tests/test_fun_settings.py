"""Profile-owned command response editing, live dispatch, and atomic persistence."""

import asyncio
import json
import logging
from types import SimpleNamespace

import pytest

from app.commands.fun import register_fun_commands
from app.commands.registry import CommandDispatcher, CommandRegistry
from app.config.commands import TG_MESSAGE
from app.fun_settings import FORECASTS, FunSettingsStore
from app.twitch.events import ChatAuthor, IncomingChatMessage
from app.utils.cooldown import CooldownManager
from app.webview_host import WebUIBridge


def test_forecast_apply_save_restart_reset_preserves_existing_profile_data(tmp_path):
    path = tmp_path / "profile" / "config" / "fun_settings.json"
    path.parent.mkdir(parents=True)
    payload = {"version": 1, "tg_message": "My community link", "forecasts": ["My local forecast"],
               "other": {"preserved": True}}
    path.write_text(json.dumps(payload), encoding="utf-8")
    store = FunSettingsStore(path)
    assert store.forecasts == ("My local forecast",)
    assert store.tg_message == "My community link"
    store.apply(["Session forecast"])
    assert store.snapshot()["saved"] is False
    assert json.loads(path.read_text()) == payload
    assert FunSettingsStore(path).forecasts == ("My local forecast",)
    store.save(["Saved forecast", "Another forecast"])
    assert store.snapshot()["saved"] is True
    assert FunSettingsStore(path).forecasts == ("Saved forecast", "Another forecast")
    store.reset()
    assert store.forecasts == FORECASTS
    assert store.snapshot()["has_saved_override"] is False
    assert json.loads(path.read_text()) == {key: value for key, value in payload.items() if key != "forecasts"}
    assert FunSettingsStore(path).tg_message == "My community link"


def test_clean_and_separate_profiles_use_neutral_defaults(tmp_path):
    one = FunSettingsStore(tmp_path / "one" / "fun_settings.json")
    two = FunSettingsStore(tmp_path / "two" / "fun_settings.json")
    assert one.forecasts == two.forecasts == FORECASTS
    assert not one.path.exists() and not two.path.exists()
    one.save(["One profile only"])
    assert FunSettingsStore(one.path).forecasts == ("One profile only",)
    assert FunSettingsStore(two.path).forecasts == FORECASTS
    one.save(["One community only"], "tg")
    assert FunSettingsStore(one.path).tg_message == "One community only"
    assert FunSettingsStore(two.path).tg_message == TG_MESSAGE
    assert not two.path.exists()


def test_tg_apply_save_restart_reset_preserves_forecasts_and_other_profile_fields(tmp_path):
    path = tmp_path / "fun_settings.json"
    payload = {"version": 1, "tg_message": "Saved community", "forecasts": ["Saved forecast"],
               "other": {"preserved": True}}
    path.write_text(json.dumps(payload), encoding="utf-8")
    store = FunSettingsStore(path)
    store.apply(["Session forecast"])
    store.apply(["Session community"], "tg")
    assert store.snapshot("tg")["saved"] is False
    assert json.loads(path.read_text()) == payload
    assert FunSettingsStore(path).tg_message == "Saved community"

    store.save(["New community, https://example.test/community"], "tg")
    assert store.snapshot("tg")["saved"] is True
    assert store.snapshot()["saved"] is False
    assert store.forecasts == ("Session forecast",)
    assert FunSettingsStore(path).forecasts == ("Saved forecast",)
    assert FunSettingsStore(path).tg_message == "New community, https://example.test/community"
    store.reset("tg")
    assert store.tg_message == TG_MESSAGE
    assert store.snapshot("tg")["has_saved_override"] is False
    assert store.forecasts == ("Session forecast",)
    assert json.loads(path.read_text()) == {key: value for key, value in payload.items() if key != "tg_message"}


@pytest.mark.parametrize("command_name", ["forecast", "tg"])
@pytest.mark.parametrize("responses", [None, "text", [], [""], ["   "], [None], ["x" * 451], ["é" * 226]])
def test_invalid_response_edits_leave_effective_and_saved_values_unchanged(tmp_path, responses, command_name):
    store = FunSettingsStore(tmp_path / "fun_settings.json")
    store.save(["Existing response"], command_name)
    before = store.path.read_bytes()
    effective = store.snapshot(command_name)
    for operation in (store.apply, store.save):
        with pytest.raises(ValueError):
            operation(responses, command_name)
        assert store.snapshot(command_name) == effective
        assert store.path.read_bytes() == before


@pytest.mark.parametrize("command_name,max_responses", [("forecast", 1000), ("tg", 1)])
def test_response_count_and_utf8_byte_boundaries(tmp_path, command_name, max_responses):
    store = FunSettingsStore(tmp_path / "fun_settings.json")
    accepted = ["é" * 225] * max_responses
    store.apply(accepted, command_name)
    assert store.snapshot(command_name)["responses"] == accepted
    with pytest.raises(ValueError):
        store.save(accepted + ["Too many"], command_name)
    assert not store.path.exists()
    assert store.snapshot(command_name)["responses"] == accepted


@pytest.mark.parametrize("command_name", ["forecast", "tg"])
@pytest.mark.parametrize("operation", ["save", "reset"])
def test_failed_atomic_replace_keeps_saved_file_and_runtime(tmp_path, monkeypatch, operation, command_name):
    store = FunSettingsStore(tmp_path / "fun_settings.json")
    store.save(["Existing response"], command_name)
    before = store.path.read_bytes()
    effective = store.snapshot(command_name)
    def fail_replace(source, target):
        raise OSError("disk failure")
    monkeypatch.setattr("app.fun_settings.os.replace", fail_replace)
    with pytest.raises(OSError):
        store.save(["New response"], command_name) if operation == "save" else store.reset(command_name)
    assert store.path.read_bytes() == before
    assert store.snapshot(command_name) == effective
    assert list(tmp_path.iterdir()) == [store.path]


@pytest.mark.parametrize("command_name", ["forecast", "tg"])
@pytest.mark.parametrize("content", ['{"version": 2, "forecasts": ["future"]}', 'not json'])
def test_unreadable_or_future_file_is_not_overwritten(tmp_path, content, command_name):
    path = tmp_path / "fun_settings.json"
    path.write_text(content)
    store = FunSettingsStore(path)
    assert store.forecasts == FORECASTS
    store.apply(["Session response"], command_name)
    with pytest.raises(ValueError, match="Repair"):
        store.save(["Replacement"], command_name)
    with pytest.raises(ValueError, match="Repair"):
        store.reset(command_name)
    assert path.read_text() == content


def test_bridge_response_editor_changes_live_forecast_only(tmp_path):
    store = FunSettingsStore(tmp_path / "fun_settings.json")
    registry = CommandRegistry()
    register_fun_commands(registry, store)
    bridge = WebUIBridge(SimpleNamespace(application=SimpleNamespace(fun_settings=store)))
    assert bridge.save_command_responses("weather", ["Invented weather"])["ok"] is False
    assert bridge.apply_command_responses("forecast", ["Live response"]) == {"ok": True}
    assert not store.path.exists()
    replies = []
    async def respond(text):
        replies.append(text)
    message = IncomingChatMessage(channel="test", content="!forecast",
                                  author=ChatAuthor(twitch_user_id="user", username="viewer"), respond=respond)
    dispatcher = CommandDispatcher(registry=registry, cooldowns=CooldownManager(),
                                   logger=logging.getLogger("tests.fun"), command_prefix="!")
    asyncio.run(dispatcher.dispatch(message, SimpleNamespace()))
    assert replies == ["@viewer, Live response"]
    assert bridge.save_command_responses("forecast", ["Saved response"]) == {"ok": True}
    assert FunSettingsStore(store.path).forecasts == ("Saved response",)
    assert bridge.reset_command_responses("forecast") == {"ok": True}
    assert store.forecasts == FORECASTS


def test_bridge_exposes_only_editable_fun_command_responses(tmp_path):
    store = FunSettingsStore(tmp_path / "fun_settings.json")
    registry = CommandRegistry()
    register_fun_commands(registry, store)
    defaults = {definition.name: definition.default_settings for definition in registry.definitions()}
    runtime_state = SimpleNamespace(
        get_command_settings=defaults.__getitem__,
        get_command_default_settings=defaults.__getitem__,
        command_settings_are_saved=lambda name: True,
        has_saved_command_override=lambda name: False,
    )
    bridge = WebUIBridge(SimpleNamespace(application=SimpleNamespace(
        fun_settings=store, registry=registry, services=SimpleNamespace(runtime_state=runtime_state),
        settings=SimpleNamespace(command_prefix="!"),
    )))
    commands = {command["name"]: command for command in bridge.get_commands()["commands"]}
    assert commands["ping"]["response_pool"] is None
    assert commands["forecast"]["response_pool"]["response_mode"] == "random"
    assert commands["forecast"]["response_pool"]["max_responses"] == 1000
    assert commands["tg"]["response_pool"]["response_mode"] == "single"
    assert commands["tg"]["response_pool"]["max_responses"] == 1
    assert commands["tg"]["response_pool"]["responses"] == [TG_MESSAGE]


@pytest.mark.parametrize("count", [1, 3, 10])
def test_bridge_tg_editor_changes_live_message_and_preserves_burst_count(tmp_path, count):
    store = FunSettingsStore(tmp_path / "fun_settings.json")
    registry = CommandRegistry()
    register_fun_commands(registry, store)
    bridge = WebUIBridge(SimpleNamespace(application=SimpleNamespace(fun_settings=store)))
    assert bridge.apply_command_responses("tg", ["Community, https://example.test"]) == {"ok": True}
    assert bridge.apply_command_responses("tg", ["One", "Two"])["ok"] is False
    assert not store.path.exists()
    replies = []
    async def respond(text):
        replies.append(text)
    message = IncomingChatMessage(channel="test", content=f"!tg {count}",
                                  author=ChatAuthor(twitch_user_id="user", username="viewer", is_moderator=True),
                                  respond=respond)
    dispatcher = CommandDispatcher(registry=registry, cooldowns=CooldownManager(),
                                   logger=logging.getLogger("tests.fun"), command_prefix="!")
    asyncio.run(dispatcher.dispatch(message, SimpleNamespace()))
    assert replies == ["Community, https://example.test"] * count
    assert bridge.save_command_responses("tg", ["Saved community"]) == {"ok": True}
    assert FunSettingsStore(store.path).tg_message == "Saved community"
    assert bridge.reset_command_responses("tg") == {"ok": True}
    assert store.tg_message == TG_MESSAGE
