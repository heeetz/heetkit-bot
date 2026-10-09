"""Fate startup migration preserves customization, originals and profile isolation."""

import json
from types import SimpleNamespace

import pytest

from app.commands.fun import register_fun_commands
from app.commands.registry import CommandRegistry
from app.config.settings import Settings
from app.fun_settings import FATES, FunSettingsStore
from app.runtime_paths import RuntimePaths
from app.runtime_state import RuntimeState
from app.twitch.permissions import Permission
from app.utils.cooldown import CooldownPolicy
from app import settings_recovery, webview_host


LEGACY_OVERRIDE = {
    "enabled": False,
    "cooldown": {"per_user_seconds": 7, "global_seconds": 31},
    "permission": "VIP",
    "future": {"keep": "é"},
}
RESPONSES = ["Моя доля, {literal}.", "My unchanged forecast"]


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    original = (json.dumps(payload, ensure_ascii=False, indent=3) + "\n").encode("utf-8")
    path.write_bytes(original)
    return original


def load_profile(root):
    paths = RuntimePaths(root)
    fun = FunSettingsStore(paths.config / "fun_settings.json")
    registry = CommandRegistry()
    register_fun_commands(registry, fun)
    state = RuntimeState(command_settings_path=paths.command_settings)
    state.configure_commands(registry.definitions())
    return fun, state, registry


def test_customized_legacy_profile_migrates_once_and_preserves_later_edits(tmp_path):
    paths = RuntimePaths(tmp_path)
    command_payload = {"forecast": LEGACY_OVERRIDE, "ping": {"enabled": False}, "unknown": ["keep"]}
    fun_payload = {"version": 1, "forecasts": RESPONSES, "tg_message": "My community", "extra": ["keep"]}
    originals = {
        paths.command_settings: write_json(paths.command_settings, command_payload),
        paths.config / "fun_settings.json": write_json(paths.config / "fun_settings.json", fun_payload),
    }
    fun, state, registry = load_profile(tmp_path)
    effective = state.get_command_settings("fate")
    assert not effective.enabled
    assert effective.cooldown == CooldownPolicy(per_user_seconds=7, global_seconds=31)
    assert effective.permission is Permission.VIP
    assert not state.get_command_settings("ping").enabled
    assert fun.fates == tuple(RESPONSES) and fun.tg_message == "My community"
    assert registry.get("forecast") is None
    assert json.loads(paths.command_settings.read_text(encoding="utf-8")) == {
        "fate": LEGACY_OVERRIDE, "ping": {"enabled": False}, "unknown": ["keep"],
    }
    assert json.loads(fun.path.read_text(encoding="utf-8")) == {
        "version": 1, "fates": RESPONSES, "tg_message": "My community", "extra": ["keep"],
    }
    migrated = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in originals}
    for path, original in originals.items():
        copies = list(path.parent.glob(f"{path.name}.*.recovery"))
        assert len(copies) == 1 and copies[0].read_bytes() == original
    for _ in range(3):
        again, restored, _ = load_profile(tmp_path)
        assert again.fates == fun.fates
        assert restored.get_command_settings("fate") == effective
        for path, (content, mtime) in migrated.items():
            assert path.read_bytes() == content and path.stat().st_mtime_ns == mtime
            assert len(list(path.parent.glob(f"{path.name}.*.recovery"))) == 1

    fun.save(["New saved fate"])
    state.save_command_settings("fate", enabled=True, cooldown=CooldownPolicy(global_seconds=19),
                                permission=Permission.SUBSCRIBER)
    again, restored, _ = load_profile(tmp_path)
    assert again.fates == ("New saved fate",)
    assert again.tg_message == "My community"
    assert json.loads(again.path.read_text(encoding="utf-8"))["extra"] == ["keep"]
    assert restored.get_command_settings("fate") == state.get_command_settings("fate")
    assert not restored.get_command_settings("ping").enabled
    saved = {path: path.read_bytes() for path in originals}
    load_profile(tmp_path)
    assert all(path.read_bytes() == content for path, content in saved.items())


@pytest.mark.parametrize("kind", ["command", "fun"])
@pytest.mark.parametrize("destination", ["custom", "empty", "invalid"])
def test_complete_destination_wins_collision_even_when_invalid(tmp_path, kind, destination):
    paths = RuntimePaths(tmp_path)
    if kind == "command":
        new = {"enabled": True} if destination == "custom" else {} if destination == "empty" else None
        path = paths.command_settings
        payload = {"forecast": LEGACY_OVERRIDE, "fate": new, "unrelated": {"keep": True}}
        old_key = "forecast"
    else:
        new = ["Destination only"] if destination == "custom" else [] if destination == "empty" else None
        path = paths.config / "fun_settings.json"
        payload = {"version": 1, "forecasts": RESPONSES, "fates": new, "unrelated": {"keep": True}}
        old_key = "forecasts"
    original = write_json(path, payload)
    fun, state, registry = load_profile(tmp_path)
    assert json.loads(path.read_text(encoding="utf-8")) == {
        key: value for key, value in payload.items() if key != old_key
    }
    if kind == "command":
        assert state.get_command_settings("fate") == registry.get("fate").default_settings
    else:
        assert fun.fates == (("Destination only",) if destination == "custom" else FATES)
    copies = list(path.parent.glob(f"{path.name}.*.recovery"))
    assert len(copies) == 1 and copies[0].read_bytes() == original


@pytest.mark.parametrize("command_migrated", [True, False])
def test_partially_migrated_profile_only_rewrites_remaining_legacy_file(tmp_path, command_migrated):
    paths = RuntimePaths(tmp_path)
    command_key = "fate" if command_migrated else "forecast"
    response_key = "forecasts" if command_migrated else "fates"
    write_json(paths.command_settings, {command_key: LEGACY_OVERRIDE})
    write_json(paths.config / "fun_settings.json", {"version": 1, response_key: RESPONSES})
    complete = paths.command_settings if command_migrated else paths.config / "fun_settings.json"
    original, mtime = complete.read_bytes(), complete.stat().st_mtime_ns
    fun, state, _ = load_profile(tmp_path)
    assert fun.fates == tuple(RESPONSES)
    assert state.get_command_settings("fate").permission is Permission.VIP
    assert complete.read_bytes() == original and complete.stat().st_mtime_ns == mtime
    assert not list(complete.parent.glob(f"{complete.name}.*.recovery"))


@pytest.mark.parametrize("kind", ["command", "fun"])
@pytest.mark.parametrize("failure", ["backup", "replace"])
def test_failed_migration_keeps_disk_and_uses_customization_for_session(tmp_path, monkeypatch, kind, failure):
    paths = RuntimePaths(tmp_path)
    path = paths.command_settings if kind == "command" else paths.config / "fun_settings.json"
    payload = {"forecast": LEGACY_OVERRIDE} if kind == "command" else {"version": 1, "forecasts": RESPONSES}
    original = write_json(path, payload)
    named_temporary = settings_recovery.tempfile.NamedTemporaryFile

    def fail_backup(*args, **kwargs):
        if kwargs.get("suffix") == ".recovery":
            raise OSError("Synthetic backup failure")
        return named_temporary(*args, **kwargs)

    def fail_replace(*args, **kwargs):
        raise OSError("Synthetic replacement failure")

    with monkeypatch.context() as patch:
        if failure == "backup":
            patch.setattr(settings_recovery.tempfile, "NamedTemporaryFile", fail_backup)
        else:
            patch.setattr(settings_recovery.os, "replace", fail_replace)
        fun, state, _ = load_profile(tmp_path)
    assert path.read_bytes() == original
    assert not list(path.parent.glob("*.tmp"))
    if kind == "command":
        assert state.get_command_settings("fate").permission is Permission.VIP
        assert not state.get_command_settings("fate").enabled
    else:
        assert fun.fates == tuple(RESPONSES)
    copies = list(path.parent.glob(f"{path.name}.*.recovery"))
    assert len(copies) == (0 if failure == "backup" else 1)
    assert all(copy.read_bytes() == original for copy in copies)
    load_profile(tmp_path)
    old_key = "forecast" if kind == "command" else "forecasts"
    assert old_key not in json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("kind", ["command", "fun"])
@pytest.mark.parametrize("content", [b"{bad", b"[]", b"\xff", b'{"forecast":{},"forecast":null,"forecasts":[],"version":1}'])
def test_malformed_files_are_never_replaced_by_migration_or_editor(tmp_path, kind, content):
    paths = RuntimePaths(tmp_path)
    path = paths.command_settings if kind == "command" else paths.config / "fun_settings.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    fun, state, _ = load_profile(tmp_path)
    assert path.read_bytes() == content
    with pytest.raises(ValueError):
        state.reset_command_settings("fate") if kind == "command" else fun.save(["Replacement"])
    assert path.read_bytes() == content
    assert not list(path.parent.glob("*.recovery"))
    assert not list(path.parent.glob("*.tmp"))


@pytest.mark.parametrize("version", [2, True, "1", None])
def test_unsupported_fun_format_is_retained(tmp_path, version):
    path = tmp_path / "config" / "fun_settings.json"
    original = write_json(path, {"version": version, "forecasts": RESPONSES})
    fun, _, _ = load_profile(tmp_path)
    assert fun.fates == FATES
    with pytest.raises(ValueError):
        fun.reset()
    assert path.read_bytes() == original
    assert not list(path.parent.glob("*.recovery"))


@pytest.mark.parametrize("selection", ["default", "environment", "legacy_environment", "cli", "check"])
def test_normal_startup_migrates_only_selected_profile_and_check_is_read_only(tmp_path, monkeypatch, selection):
    default = tmp_path / "default"
    selected = default if selection in ("default", "check") else tmp_path / "selected"
    other = tmp_path / "unselected"
    originals = {}
    for root in (selected, other):
        paths = RuntimePaths(root)
        originals[paths.command_settings] = write_json(paths.command_settings, {"forecast": LEGACY_OVERRIDE})
        path = paths.config / "fun_settings.json"
        originals[path] = write_json(path, {"version": 1, "forecasts": RESPONSES})
    monkeypatch.delenv("HEETKIT_DATA_DIR", raising=False)
    monkeypatch.delenv("TWITCH_BOT_DATA_DIR", raising=False)
    monkeypatch.setattr("app.runtime_paths.user_data_path",
                        lambda name, **kwargs: default if name == "HeetKit" else tmp_path / "former")
    prepare = webview_host.prepare_runtime_data
    monkeypatch.setattr(webview_host, "prepare_runtime_data",
                        lambda *args: prepare(*args, legacy_data=None, migrate_legacy=False))
    if selection == "environment":
        monkeypatch.setenv("HEETKIT_DATA_DIR", str(selected))
    elif selection == "legacy_environment":
        monkeypatch.setenv("TWITCH_BOT_DATA_DIR", str(selected))
    elif selection == "cli":
        monkeypatch.setenv("HEETKIT_DATA_DIR", str(other))
    args = ["heetkit", "--stopped"]
    if selection == "cli":
        args += ["--data-dir", str(selected)]
    elif selection == "check":
        args += ["--check"]
    monkeypatch.setattr("sys.argv", args)
    monkeypatch.setattr(webview_host, "ensure_windows_runtime", lambda: None)
    monkeypatch.setattr(webview_host, "configure_logging", lambda *args: None)
    monkeypatch.setattr(webview_host, "resolve_frontend_url", lambda *args: "file:///synthetic/index.html")
    settings = Settings(_env_file=None, database_url="sqlite+aiosqlite:///:memory:")
    monkeypatch.setattr(webview_host, "load_settings_with_credentials", lambda *args: (settings, SimpleNamespace()))
    opened = []

    def open_host(*args, **kwargs):
        assert RuntimePaths.default().root == selected
        fun, state, _ = load_profile(RuntimePaths.default().root)
        assert fun.fates == tuple(RESPONSES)
        assert state.get_command_settings("fate").permission is Permission.VIP
        opened.append(True)

    monkeypatch.setattr(webview_host, "run_desktop_host", open_host)
    webview_host.main()
    assert opened == ([] if selection == "check" else [True])
    for path, original in originals.items():
        if selection == "check" or path.is_relative_to(other):
            assert path.read_bytes() == original
            assert not list(path.parent.glob(f"{path.name}.*.recovery"))
        else:
            copies = list(path.parent.glob(f"{path.name}.*.recovery"))
            assert len(copies) == 1 and copies[0].read_bytes() == original


def test_fun_save_keeps_external_edits_in_recovery_after_migration(tmp_path):
    path = tmp_path / "config" / "fun_settings.json"
    write_json(path, {"version": 1, "forecasts": RESPONSES})
    fun, _, _ = load_profile(tmp_path)
    external = write_json(path, {"version": 1, "fates": ["External edit"], "future": "keep"})
    fun.save(["Editor change"])
    assert FunSettingsStore(path).fates == ("Editor change",)
    assert external in {copy.read_bytes() for copy in path.parent.glob(f"{path.name}.*.recovery")}
