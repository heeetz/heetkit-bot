"""Recovered profile snapshots must never silently discard the source data."""

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.app_settings import AppSettingsStore
from app.commands.registry import CommandRegistry
from app.custom_commands import CustomCommandStore
from app.runtime_state import RuntimeState
from app.webview_host import WebUIBridge


KINDS = ("app", "command", "personality", "profile_instructions", "custom")
CUSTOM_ID = "d309228e-92a3-422a-8284-70f52c41cce7"


def custom_payload(name="alpha", **extra):
    return {
        "id": CUSTOM_ID, "name": name, "enabled": True, "responses": ["Hello"],
        "permission": "USER", "per_user_seconds": 0, "global_seconds": 0,
        "aliases": [], **extra,
    }


def source_payload(kind):
    return {
        "app": {"version": 1, "window": {"start_minimized": True}},
        "command": {"alpha": {"enabled": False}},
        "personality": {"active_personality": "neutral", "overrides": {"neutral": "Original prompt"}},
        "profile_instructions": {
            "active_personality": "neutral", "overrides": {"neutral": "Original prompt"},
            "profile_instructions": "Original profile instructions",
        },
        "custom": {"version": 1, "commands": [custom_payload()]},
    }[kind]


def editor(kind, path):
    if kind == "app":
        store = AppSettingsStore(path)
        return SimpleNamespace(
            snapshot=store.snapshot, save=lambda: store.update_ai_memory(enabled=False),
        )
    if kind == "custom":
        store = CustomCommandStore(path, set())
        new_command = custom_payload("beta")
        new_command.pop("id")
        return SimpleNamespace(
            snapshot=store.list, save=lambda: store.save(new_command),
            reset=lambda: store.delete(CUSTOM_ID),
        )
    state = RuntimeState(
        command_settings_path=path if kind == "command" else None,
        personality_settings_path=path if kind in ("personality", "profile_instructions") else None,
    )
    if kind == "profile_instructions":
        return SimpleNamespace(
            snapshot=lambda: (state.active_ai_personality, state.get_ai_personality_prompt("neutral"),
                              state.profile_instructions, state.profile_instructions_are_saved),
            save=lambda: state.save_profile_instructions("New profile instructions"),
            reset=state.reset_profile_instructions, state=state,
        )
    if kind == "personality":
        return SimpleNamespace(
            snapshot=lambda: (state.active_ai_personality, state.get_ai_personality_prompt("neutral")),
            save=lambda: state.save_ai_personality("neutral", "New prompt"),
            reset=lambda: state.reset_ai_personality("neutral"), state=state,
        )
    registry = CommandRegistry()
    for name in ("alpha", "beta"):
        async def handler(context, arguments):
            pass
        registry.command(name)(handler)
    state.configure_commands(registry.definitions())
    return SimpleNamespace(
        snapshot=lambda: tuple(state.get_command_settings(name) for name in ("alpha", "beta")),
        save=lambda: state.save_command_settings(
            "beta", enabled=False, cooldown=registry.get("beta").default_settings.cooldown,
            permission=registry.get("beta").default_settings.permission,
        ),
        reset=lambda: state.reset_command_settings("beta"), state=state,
    )


def write_source(path, payload):
    # Formatting and non-ASCII text must survive exactly in recovery files.
    path.write_bytes((json.dumps(payload, ensure_ascii=False, indent=3) + "\n").encode("utf-8"))
    return path.read_bytes()


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("content", [b"{bad", b"[]", b"\xff", b'{"duplicate": 1, "duplicate": 2}'])
def test_unreadable_or_malformed_file_survives_unrelated_save(tmp_path, kind, content):
    path = tmp_path / f"{kind}_settings.json"
    path.write_bytes(content)
    session = editor(kind, path)
    before = session.snapshot()
    with pytest.raises(ValueError, match="Quit the app, back up and repair"):
        session.save()
    assert path.read_bytes() == content
    assert session.snapshot() == before
    assert list(tmp_path.glob("*.recovery")) == []
    assert list(tmp_path.glob("*.tmp")) == []


@pytest.mark.parametrize("kind", ("app", "custom"))
@pytest.mark.parametrize("version", [99, True, "1", None])
def test_future_or_invalid_version_survives_save(tmp_path, kind, version):
    path = tmp_path / f"{kind}_settings.json"
    original = write_source(path, {**source_payload(kind), "version": version, "future": "é"})
    session = editor(kind, path)
    before = session.snapshot()
    with pytest.raises(ValueError, match="Cannot save"):
        session.save()
    assert session.snapshot() == before
    assert path.read_bytes() == original
    assert list(tmp_path.glob("*.recovery")) == []


@pytest.mark.parametrize("kind", KINDS)
def test_read_failure_at_startup_and_at_save_preserves_original(tmp_path, monkeypatch, kind):
    path = tmp_path / f"{kind}_settings.json"
    original = write_source(path, source_payload(kind))
    read_text = Path.read_text
    read_bytes = Path.read_bytes

    def denied_text(self, *args, **kwargs):
        if self == path:
            raise PermissionError("Synthetic unreadable profile")
        return read_text(self, *args, **kwargs)

    def denied_bytes(self):
        if self == path:
            raise PermissionError("Synthetic unreadable profile")
        return read_bytes(self)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_text", denied_text)
        session = editor(kind, path)
        before = session.snapshot()
        patch.setattr(Path, "read_bytes", denied_bytes)
        with pytest.raises(ValueError, match="Cannot save"):
            session.save()
        assert session.snapshot() == before
    assert path.read_bytes() == original
    # If access returns, the recovered startup snapshot still cannot erase the
    # original customization: it must be preserved before saving defaults.
    session.save()
    copies = list(tmp_path.glob("*.recovery"))
    assert len(copies) == 1
    assert copies[0].read_bytes() == original


def lossy_payload(kind):
    payload = source_payload(kind)
    if kind == "app":
        payload["window"]["close_to_tray"] = "invalid"
        payload["twitch"] = {"presets": [{
            "id": "target", "display_name": "Example", "channel": "example",
            "channel_user_id": "123", "future_preset_field": "é",
        }]}
    elif kind == "command":
        payload["alpha"]["cooldown"] = {"global_seconds": -1, "future_field": 2}
        payload["retired_command"] = {"enabled": False}
    elif kind in ("personality", "profile_instructions"):
        payload["overrides"]["broken"] = ["invalid prompt"]
        payload["profile_instructions"] = ["invalid profile instructions"]
    else:
        payload["commands"][0]["future_field"] = {"metadata": "é"}
        payload["commands"].append({"id": "unrecoverable"})
    payload["future_section"] = {"retain": "é"}
    return payload


@pytest.mark.parametrize("kind", KINDS)
def test_unknown_fields_and_skipped_data_get_exact_unique_recovery_copy(tmp_path, kind):
    path = tmp_path / f"{kind}_settings.json"
    original = write_source(path, lossy_payload(kind))
    session = editor(kind, path)
    session.save()
    copies = list(tmp_path.glob("*.recovery"))
    assert len(copies) == 1
    assert copies[0].read_bytes() == original
    # Ordinary subsequent edits do not generate unnecessary recovery copies.
    session.reset() if kind != "app" else session.save()
    assert list(tmp_path.glob("*.recovery")) == copies
    assert copies[0].read_bytes() == original
    second_original = write_source(path, {**lossy_payload(kind), "another_future": True})
    editor(kind, path).save()
    assert {copy.read_bytes() for copy in tmp_path.glob("*.recovery")} == {original, second_original}


@pytest.mark.parametrize("kind", KINDS)
def test_supported_save_reloads_without_recovery_copy(tmp_path, kind):
    path = tmp_path / f"{kind}_settings.json"
    write_source(path, source_payload(kind))
    session = editor(kind, path)
    session.save()
    assert editor(kind, path).snapshot() == session.snapshot()
    assert list(tmp_path.glob("*.recovery")) == []
    assert list(tmp_path.glob("*.tmp")) == []


@pytest.mark.parametrize("kind", KINDS)
def test_failed_atomic_replace_preserves_disk_and_effective_state(tmp_path, monkeypatch, kind):
    path = tmp_path / f"{kind}_settings.json"
    original = write_source(path, source_payload(kind))
    session = editor(kind, path)
    before = session.snapshot()

    def fail_replace(*args, **kwargs):
        raise OSError("Synthetic replacement failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="replacement failure"):
        session.save()
    assert path.read_bytes() == original
    assert session.snapshot() == before
    assert list(tmp_path.glob("*.tmp")) == []


@pytest.mark.parametrize("kind", KINDS)
def test_failed_recovery_copy_aborts_replacement(tmp_path, monkeypatch, kind):
    import app.settings_recovery as recovery

    path = tmp_path / f"{kind}_settings.json"
    original = write_source(path, lossy_payload(kind))
    session = editor(kind, path)
    before = session.snapshot()
    named_temporary_file = recovery.tempfile.NamedTemporaryFile

    def fail_recovery_file(*args, **kwargs):
        if kwargs.get("suffix") == ".recovery":
            raise OSError("Synthetic recovery copy failure")
        return named_temporary_file(*args, **kwargs)

    monkeypatch.setattr(recovery.tempfile, "NamedTemporaryFile", fail_recovery_file)
    with pytest.raises(OSError, match="recovery copy failure"):
        session.reset() if kind != "app" else session.save()
    assert path.read_bytes() == original
    assert session.snapshot() == before
    assert list(tmp_path.glob("*.tmp")) == []


def test_command_reset_bridge_explains_repair_instead_of_losing_file(tmp_path):
    path = tmp_path / "command_settings.json"
    path.write_bytes(b"{bad")
    session = editor("command", path)
    bridge = WebUIBridge(SimpleNamespace(application=SimpleNamespace(
        services=SimpleNamespace(runtime_state=session.state),
    )))
    result = bridge.reset_command_settings("beta")
    assert result["ok"] is False
    assert "Quit the app, back up and repair" in result["error"]
    assert path.read_bytes() == b"{bad"


@pytest.mark.parametrize("kind", ("command", "personality", "profile_instructions", "custom"))
def test_reset_or_delete_refuses_file_that_became_unreadable(tmp_path, kind):
    path = tmp_path / f"{kind}_settings.json"
    write_source(path, source_payload(kind))
    session = editor(kind, path)
    before = session.snapshot()
    path.write_bytes(b"{bad")
    with pytest.raises(ValueError, match="Cannot save"):
        session.reset()
    assert session.snapshot() == before
    assert path.read_bytes() == b"{bad"
