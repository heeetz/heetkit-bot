"""Tests for the control-panel thread lifecycle without creating a Tk display."""

import threading

from app.control_panel import ControlPanel
from app.runtime_state import RuntimeState


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
