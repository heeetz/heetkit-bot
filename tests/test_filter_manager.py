"""Bounded execution for configured message-filter patterns."""

import pytest

from app.services import filter_manager as filter_manager_module
from app.services.filter_manager import FilterManager


def test_regex_timeout_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = FilterManager()

    class TimedOutPattern:
        def search(self, message: str, *, timeout: float) -> None:
            raise TimeoutError

    manager._compiled_patterns = [TimedOutPattern()]

    assert manager.contains_blocked_content("ordinary chat")


def test_regex_budget_is_shared_across_patterns(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = FilterManager()
    manager.add_blocked_pattern("first")
    manager.add_blocked_pattern("second")
    calls: list[float] = []

    class NonMatchingPattern:
        def search(self, message: str, *, timeout: float) -> None:
            calls.append(timeout)
            return None

    manager._compiled_patterns = [NonMatchingPattern(), NonMatchingPattern()]
    clock = iter((100.0, 100.01, 100.02))
    monkeypatch.setattr(filter_manager_module.time, "monotonic", lambda: next(clock))

    assert not manager.contains_blocked_content("ordinary chat")
    assert calls == pytest.approx([0.04, 0.03])
