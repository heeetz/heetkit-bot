"""Fate settings preserve malformed input and externally changed responses."""

import json

import pytest

from app.commands.fun import register_fun_commands
from app.commands.registry import CommandRegistry
from app.fun_settings import FATES, FunSettingsStore
from app.runtime_paths import RuntimePaths
from app.runtime_state import RuntimeState


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


@pytest.mark.parametrize("kind", ["command", "fun"])
@pytest.mark.parametrize("content", [b"{bad", b"[]", b"\xff", b'{"fate":{},"fate":null,"fates":[],"version":1}'])
def test_malformed_files_are_never_replaced_by_editor(tmp_path, kind, content):
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
    original = write_json(path, {"version": version, "fates": RESPONSES})
    fun, _, _ = load_profile(tmp_path)
    assert fun.fates == FATES
    with pytest.raises(ValueError):
        fun.reset()
    assert path.read_bytes() == original
    assert not list(path.parent.glob("*.recovery"))


def test_fun_save_keeps_external_edits_in_recovery(tmp_path):
    path = tmp_path / "config" / "fun_settings.json"
    write_json(path, {"version": 1, "fates": RESPONSES})
    fun, _, _ = load_profile(tmp_path)
    external = write_json(path, {"version": 1, "fates": ["External edit"], "future": "keep"})
    fun.save(["Editor change"])
    assert FunSettingsStore(path).fates == ("Editor change",)
    assert external in {copy.read_bytes() for copy in path.parent.glob(f"{path.name}.*.recovery")}
