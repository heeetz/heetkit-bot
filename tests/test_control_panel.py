"""Tests for the control-panel thread lifecycle without creating a Tk display."""

import threading

from app.commands.ai import register_ai_commands
from app.commands.fun import register_fun_commands
from app.commands.info import register_info_commands, register_weather_commands
from app.commands.registry import CommandRegistry
from app.commands.social import register_social_commands
from app.control_panel import ControlPanel
from app.runtime_state import RuntimeState


def build_registered_runtime_state() -> tuple[CommandRegistry, RuntimeState]:
    registry = CommandRegistry()
    register_fun_commands(registry)
    register_weather_commands(registry)
    register_info_commands(registry)
    register_ai_commands(registry)
    register_social_commands(registry)
    runtime_state = RuntimeState()
    runtime_state.configure_commands(
        definition.name for definition in registry.definitions()
    )
    return registry, runtime_state


def test_panel_receives_every_registered_runtime_command() -> None:
    registry, runtime_state = build_registered_runtime_state()
    panel = ControlPanel(runtime_state, on_stop=lambda: None)

    expected = tuple(definition.name for definition in registry.definitions())

    assert runtime_state.runtime_toggleable_commands == expected
    assert panel._command_names() == expected
    assert "erase" in expected


def test_panel_command_toggle_updates_runtime_state() -> None:
    _, runtime_state = build_registered_runtime_state()
    panel = ControlPanel(runtime_state, on_stop=lambda: None)

    panel._set_command_enabled("ping", False)

    assert runtime_state.command_enabled("ping") is False
    assert runtime_state.is_command_enabled("ping") is False


def test_panel_uses_runtime_state_for_new_command_names() -> None:
    runtime_state = RuntimeState()
    runtime_state.configure_commands(("existing", "future"))
    panel = ControlPanel(runtime_state, on_stop=lambda: None)

    assert panel._command_names() == ("existing", "future")


def test_control_panel_stop_signals_and_joins_its_worker_thread(
    monkeypatch,
) -> None:
    panel = ControlPanel(RuntimeState(), on_stop=lambda: None)
    started = threading.Event()
    stopped = threading.Event()

    def run() -> None:
        started.set()
        assert panel._actions.get() == "close"
        stopped.set()

    monkeypatch.setattr(panel, "_run", run)

    panel.start()
    worker = panel._thread
    assert worker is not None
    assert worker.daemon is False
    assert started.wait(timeout=1.0)

    panel.stop()

    assert stopped.is_set()
    assert worker.is_alive() is False
    assert panel._thread is None
