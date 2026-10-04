"""Profile-owned forecast editing, live dispatch, and atomic persistence."""

import asyncio
import json
import logging
from types import SimpleNamespace

import pytest

from app.commands.fun import register_fun_commands
from app.commands.registry import CommandDispatcher, CommandRegistry
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
    assert not two.path.exists()


@pytest.mark.parametrize("responses", [None, "text", [], [""], ["   "], [None], ["x" * 451], ["é" * 226]])
def test_invalid_response_edits_leave_effective_and_saved_values_unchanged(tmp_path, responses):
    store = FunSettingsStore(tmp_path / "fun_settings.json")
    store.save(["Existing response"])
    before = store.path.read_bytes()
    for operation in (store.apply, store.save):
        with pytest.raises(ValueError):
            operation(responses)
        assert store.forecasts == ("Existing response",)
        assert store.path.read_bytes() == before


@pytest.mark.parametrize("operation", ["save", "reset"])
def test_failed_atomic_replace_keeps_saved_file_and_runtime(tmp_path, monkeypatch, operation):
    store = FunSettingsStore(tmp_path / "fun_settings.json")
    store.save(["Existing response"])
    before = store.path.read_bytes()
    def fail_replace(source, target):
        raise OSError("disk failure")
    monkeypatch.setattr("app.fun_settings.os.replace", fail_replace)
    with pytest.raises(OSError):
        store.save(["New response"]) if operation == "save" else store.reset()
    assert store.path.read_bytes() == before
    assert store.forecasts == ("Existing response",)
    assert list(tmp_path.iterdir()) == [store.path]


@pytest.mark.parametrize("content", ['{"version": 2, "forecasts": ["future"]}', 'not json'])
def test_unreadable_or_future_file_is_not_overwritten(tmp_path, content):
    path = tmp_path / "fun_settings.json"
    path.write_text(content)
    store = FunSettingsStore(path)
    assert store.forecasts == FORECASTS
    store.apply(["Session response"])
    with pytest.raises(ValueError, match="Repair"):
        store.save(["Replacement"])
    with pytest.raises(ValueError, match="Repair"):
        store.reset()
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
