"""Bounded execution for configured message-filter patterns."""

import pytest

from app.services import filter_manager as filter_manager_module
from app.services.filter_manager import FilterManager, FilterRule


def test_regex_timeout_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = FilterManager()
    manager.add_blocked_pattern("synthetic")

    class TimedOutPattern:
        def search(self, message: str, *, timeout: float) -> None:
            raise TimeoutError

    manager._compiled_patterns = [TimedOutPattern()]

    assert manager.contains_blocked_content("ordinary chat")
    result = manager.evaluate_message("ordinary chat")
    assert not result.allowed
    assert result.category == "patterns"
    assert result.rule == "synthetic"
    assert result.timed_out


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


@pytest.mark.parametrize(
    ("text", "category", "rule"),
    [
        ("ALPHA, good game!", "words", "alpha"),
        ("Привет, ТЕСТ", "words", "тест"),
        ("Це ПРИКЛАД!", "words", "приклад"),
        ("Get FREE FOLLOWERS here", "phrases", "free followers"),
        ("Первая строка\nПЛОХАЯ ФРАЗА\nтретья", "phrases", "плохая фраза"),
        ("Це НЕБАЖАНА ФРАЗА", "phrases", "небажана фраза"),
        ("prefix BAD123 suffix", "patterns", r"bad\d+"),
        ("Alphabet and tests are harmless", None, None),
        ("", None, None),
    ],
)
def test_evaluation_reports_the_rule_used_by_live_filtering(text, category, rule) -> None:
    manager = FilterManager()
    manager.replace_blocked_words(["alpha", "тест", "приклад"])
    manager.replace_blocked_phrases(["free followers", "плохая фраза", "небажана фраза"])
    manager.add_blocked_pattern(r"bad\d+")

    result = manager.evaluate_message(text)

    assert result.allowed is (category is None)
    assert result.category == category
    assert result.rule == rule
    assert not result.timed_out
    assert manager.filter_message(text) is result.allowed
    assert manager.contains_blocked_content(text) is (not result.allowed)


def test_evaluation_keeps_first_match_order_and_pattern_flags() -> None:
    manager = FilterManager()
    manager.add_blocked_word("first")
    manager.add_blocked_phrase("first phrase")
    manager.replace_blocked_patterns([
        FilterRule("Exact.Text", is_regex=False, case_sensitive=True),
        FilterRule("first"),
    ])

    assert manager.evaluate_message("first phrase").category == "words"
    assert manager.evaluate_message("exact.text").allowed
    assert manager.evaluate_message("ExactXText").allowed
    assert manager.evaluate_message("Exact.Text").rule == "Exact.Text"


def test_budget_exhaustion_is_reported_without_claiming_a_rule_matched(monkeypatch) -> None:
    manager = FilterManager()
    manager.add_blocked_pattern("first")
    manager.add_blocked_pattern("second")
    calls = []

    class NonMatchingPattern:
        def search(self, message: str, *, timeout: float) -> None:
            calls.append(timeout)

    manager._compiled_patterns = [NonMatchingPattern(), NonMatchingPattern()]
    clock = iter((100.0, 100.01, 100.06))
    monkeypatch.setattr(filter_manager_module.time, "monotonic", lambda: next(clock))

    result = manager.evaluate_message("ordinary chat")

    assert not result.allowed
    assert result.category == "patterns"
    assert result.rule is None
    assert result.timed_out
    assert calls == pytest.approx([0.04])
