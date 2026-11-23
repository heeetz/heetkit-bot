"""Profile-owned command response editing, live dispatch, and atomic persistence."""

import asyncio
import logging
from types import SimpleNamespace

import pytest

from app.commands.fun import register_fun_commands
from app.commands.registry import CommandDispatcher, CommandRegistry
from app.fun_settings import FATES, FunSettingsStore
from app.twitch.events import ChatAuthor, IncomingChatMessage
from app.utils.cooldown import CooldownManager
from app.webview_host import WebUIBridge
from app.config_file import ConfigFile
from config_helpers import read_section, write_section


def test_fate_apply_save_restart_reset_preserves_existing_profile_data(tmp_path):
    path = tmp_path / "profile" / "config" / "fun_settings.json"
    path.parent.mkdir(parents=True)
    payload = {"version": 1, "fates": ["My local forecast"],
               "other": {"preserved": True}}
    write_section(path, "fun", payload)
    store = FunSettingsStore(ConfigFile(path))
    assert store.fates == ("My local forecast",)
    store.apply(["Session forecast"])
    assert store.snapshot()["saved"] is False
    assert read_section(path, "fun") == payload
    assert FunSettingsStore(ConfigFile(path)).fates == ("My local forecast",)
    store.save(["Saved forecast", "Another forecast"])
    assert store.snapshot()["saved"] is True
    assert FunSettingsStore(ConfigFile(path)).fates == ("Saved forecast", "Another forecast")
    store.reset()
    assert store.fates == FATES
    assert store.snapshot()["has_saved_override"] is False
    assert read_section(path, "fun") == {key: value for key, value in payload.items() if key != "fates"}


def test_clean_and_separate_profiles_use_neutral_defaults(tmp_path):
    one = FunSettingsStore(ConfigFile(tmp_path / "one" / "fun_settings.json"))
    two = FunSettingsStore(ConfigFile(tmp_path / "two" / "fun_settings.json"))
    assert one.fates == two.fates == FATES
    assert not one.section.path.exists() and not two.section.path.exists()
    one.save(["One profile only"])
    assert FunSettingsStore(ConfigFile(one.section.path)).fates == ("One profile only",)
    assert FunSettingsStore(ConfigFile(two.section.path)).fates == FATES
    assert not two.section.path.exists()


@pytest.mark.parametrize("command_name", ["fate"])
@pytest.mark.parametrize("responses", [None, "text", [], [""], ["   "], [None], ["x" * 451], ["é" * 226]])
def test_invalid_response_edits_leave_effective_and_saved_values_unchanged(tmp_path, responses, command_name):
    store = FunSettingsStore(ConfigFile(tmp_path / "fun_settings.json"))
    store.save(["Existing response"], command_name)
    before = store.section.path.read_bytes()
    effective = store.snapshot(command_name)
    for operation in (store.apply, store.save):
        with pytest.raises(ValueError):
            operation(responses, command_name)
        assert store.snapshot(command_name) == effective
        assert store.section.path.read_bytes() == before


@pytest.mark.parametrize("command_name,max_responses", [("fate", 1000)])
def test_response_count_and_utf8_byte_boundaries(tmp_path, command_name, max_responses):
    store = FunSettingsStore(ConfigFile(tmp_path / "fun_settings.json"))
    accepted = ["é" * 225] * max_responses
    store.apply(accepted, command_name)
    assert store.snapshot(command_name)["responses"] == accepted
    with pytest.raises(ValueError):
        store.save(accepted + ["Too many"], command_name)
    assert not store.section.path.exists()
    assert store.snapshot(command_name)["responses"] == accepted


@pytest.mark.parametrize("command_name", ["fate"])
@pytest.mark.parametrize("operation", ["save", "reset"])
def test_failed_atomic_replace_keeps_saved_file_and_runtime(tmp_path, monkeypatch, operation, command_name):
    store = FunSettingsStore(ConfigFile(tmp_path / "fun_settings.json"))
    store.save(["Existing response"], command_name)
    before = store.section.path.read_bytes()
    effective = store.snapshot(command_name)
    def fail_replace(source, target):
        raise OSError("disk failure")
    monkeypatch.setattr("app.config_file.os.replace", fail_replace)
    with pytest.raises(OSError):
        store.save(["New response"], command_name) if operation == "save" else store.reset(command_name)
    assert store.section.path.read_bytes() == before
    assert store.snapshot(command_name) == effective
    assert list(tmp_path.iterdir()) == [store.section.path]


@pytest.mark.parametrize("command_name", ["fate"])
@pytest.mark.parametrize("content", ['{"schema_version": 1, "fun": {"version": 2, "fates": ["future"]}}', 'not json'])
def test_unreadable_or_future_file_is_not_overwritten(tmp_path, content, command_name):
    path = tmp_path / "fun_settings.json"
    path.write_text(content)
    store = FunSettingsStore(ConfigFile(path))
    assert store.fates == FATES
    store.apply(["Session response"], command_name)
    with pytest.raises(ValueError) as error:
        store.save(["Replacement"], command_name)
    assert error.value.code == "fun_settings.repair_unreadable_unsupported_fun_settings_json"
    with pytest.raises(ValueError) as error:
        store.reset(command_name)
    assert error.value.code == "fun_settings.repair_unreadable_unsupported_fun_settings_json"
    assert path.read_text() == content


def test_bridge_response_editor_changes_live_fate_only(tmp_path):
    store = FunSettingsStore(ConfigFile(tmp_path / "fun_settings.json"))
    registry = CommandRegistry()
    register_fun_commands(registry, store)
    bridge = WebUIBridge(SimpleNamespace(application=SimpleNamespace(fun_settings=store)))
    assert bridge.save_command_responses("weather", ["Invented weather"])["ok"] is False
    assert bridge.apply_command_responses("forecast", ["Old name"])["ok"] is False
    assert bridge.save_command_responses("forecast", ["Old name"])["ok"] is False
    assert bridge.reset_command_responses("forecast")["ok"] is False
    assert bridge.apply_command_responses("fate", ["Live response"]) == {"ok": True}
    assert not store.section.path.exists()
    replies = []
    async def respond(text):
        replies.append(text)
    message = IncomingChatMessage(channel="test", content="!fate",
                                  author=ChatAuthor(twitch_user_id="user", username="viewer"), respond=respond)
    dispatcher = CommandDispatcher(registry=registry, cooldowns=CooldownManager(),
                                   logger=logging.getLogger("tests.fun"), command_prefix="!")
    asyncio.run(dispatcher.dispatch(message, SimpleNamespace()))
    assert replies == ["@viewer, Live response"]
    assert bridge.save_command_responses("fate", ["Saved response"]) == {"ok": True}
    assert FunSettingsStore(ConfigFile(store.section.path)).fates == ("Saved response",)
    assert bridge.reset_command_responses("fate") == {"ok": True}
    assert store.fates == FATES


def test_bridge_exposes_only_editable_fun_command_responses(tmp_path):
    store = FunSettingsStore(ConfigFile(tmp_path / "fun_settings.json"))
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
    assert commands["fate"]["response_pool"]["response_mode"] == "random"
    assert commands["fate"]["response_pool"]["max_responses"] == 1000


