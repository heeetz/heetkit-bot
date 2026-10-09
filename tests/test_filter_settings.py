"""Desktop filter editing keeps the existing moderation and loader behavior."""

import asyncio
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.filter_settings import (
    apply_filter_settings,
    evaluate_filter_settings,
    get_filter_settings,
    save_filter_settings,
    validate_filter_input,
)
from app.services.filter_loader import load_filters_from_directory
from app.services.filter_manager import FilterManager
from app.webview_host import BridgeOperationTimedOut, WebUIBridge


def _files(directory: Path, words: str, phrases: str, patterns: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for filename, contents in zip(
        ("blocked_words.txt", "blocked_phrases.txt", "blocked_patterns.txt"),
        (words, phrases, patterns),
    ):
        (directory / filename).write_text(contents, encoding="utf-8")


def test_inspection_marks_source_and_local_rules_and_invalid_regex(tmp_path: Path) -> None:
    defaults = tmp_path / "defaults"
    local = tmp_path / "local"
    _files(defaults, "alpha\n", "source phrase\n", "source[0-9]+\n")
    _files(local, "alpha\nbeta\n", "local phrase\n", "broken[\nsource[0-9]+\n")
    manager = FilterManager()
    load_filters_from_directory(manager, local)

    state = get_filter_settings(manager, local, defaults)

    assert state["words"]["rules"] == [
        {"value": "alpha", "valid": True, "error": None, "origin": "default"},
        {"value": "beta", "valid": True, "error": None, "origin": "local"},
    ]
    assert state["phrases"]["rules"][0]["origin"] == "local"
    assert state["patterns"]["rules"][0]["valid"] is False
    assert "Invalid regex" in state["patterns"]["rules"][0]["error"]
    assert state["patterns"]["rules"][1]["origin"] == "default"
    assert not manager.filter_message("source42")


def test_invalid_apply_does_not_change_valid_active_rules() -> None:
    manager = FilterManager()
    manager.add_blocked_word("existing")
    payload = {"words": ["new"], "phrases": [], "patterns": ["broken["]}

    with pytest.raises(ValueError, match="Invalid regex"):
        apply_filter_settings(manager, validate_filter_input(payload))

    assert not manager.filter_message("existing")
    assert manager.filter_message("new")


def test_save_reloads_with_exact_prior_matching_semantics(tmp_path: Path) -> None:
    manager = FilterManager()
    payload = {
        "words": ["alpha", "alpha"],
        "phrases": ["free followers"],
        "patterns": [r"bad\d+"],
    }
    save_filter_settings(manager, validate_filter_input(payload), tmp_path)
    reloaded = FilterManager()
    load_filters_from_directory(reloaded, tmp_path)

    for active in (manager, reloaded):
        assert not active.filter_message("ALPHA")
        assert active.filter_message("alphabet")
        assert not active.filter_message("Get FREE FOLLOWERS")
        assert not active.filter_message("BAD123")
    assert (tmp_path / "blocked_words.txt").read_text(encoding="utf-8") == "alpha\n"


def test_save_keeps_untouched_file_comments(tmp_path: Path) -> None:
    _files(tmp_path, "# source note\nalpha\n", "phrase\n", "pattern\n")
    manager = FilterManager()
    payload = {"words": ["alpha"], "phrases": ["updated"], "patterns": ["pattern"]}

    save_filter_settings(manager, validate_filter_input(payload), tmp_path)

    assert (tmp_path / "blocked_words.txt").read_text(encoding="utf-8") == "# source note\nalpha\n"
    assert (tmp_path / "blocked_phrases.txt").read_text(encoding="utf-8") == "updated\n"


def test_failed_multi_file_save_restores_previous_files(tmp_path: Path, monkeypatch) -> None:
    _files(tmp_path, "old word\n", "old phrase\n", "old.*\n")
    manager = FilterManager()
    load_filters_from_directory(manager, tmp_path)
    original_replace = Path.replace
    failed = False

    def fail_second_replace(self: Path, target: Path):
        nonlocal failed
        if target == tmp_path / "blocked_phrases.txt" and not failed:
            failed = True
            raise PermissionError("denied")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_second_replace)
    payload = {"words": ["new word"], "phrases": ["new phrase"], "patterns": ["new.*"]}

    with pytest.raises(PermissionError):
        save_filter_settings(manager, validate_filter_input(payload), tmp_path)

    assert (tmp_path / "blocked_words.txt").read_text(encoding="utf-8") == "old word\n"
    assert (tmp_path / "blocked_phrases.txt").read_text(encoding="utf-8") == "old phrase\n"
    assert not manager.filter_message("old word")
    assert manager.filter_message("new word")


def test_unreadable_file_shows_active_rules_and_error(tmp_path: Path) -> None:
    defaults = tmp_path / "defaults"
    local = tmp_path / "local"
    _files(defaults, "", "", "")
    _files(local, "", "", "")
    manager = FilterManager()
    manager.add_blocked_word("protected")
    (local / "blocked_words.txt").unlink()

    state = get_filter_settings(manager, local, defaults)

    assert state["words"]["load_error"]
    assert state["words"]["rules"][0]["value"] == "protected"
    assert not manager.filter_message("protected")


def test_invalid_only_file_shows_retained_active_rules(tmp_path: Path) -> None:
    defaults = tmp_path / "defaults"
    local = tmp_path / "local"
    _files(defaults, "", "", "")
    _files(local, "", "", "valid.*\n")
    manager = FilterManager()
    load_filters_from_directory(manager, local)
    (local / "blocked_patterns.txt").write_text("broken[\n", encoding="utf-8")
    load_filters_from_directory(manager, local)

    state = get_filter_settings(manager, local, defaults)

    assert state["patterns"]["load_error"]
    assert [entry["value"] for entry in state["patterns"]["rules"]] == ["broken[", "valid.*"]
    assert not manager.filter_message("valid text")


def test_bridge_rejects_invalid_regex_and_applies_valid_rules() -> None:
    manager = FilterManager()

    class Backend:
        application = SimpleNamespace(services=SimpleNamespace(filter_manager=manager))

        @staticmethod
        def submit(coroutine) -> Future:
            future: Future = Future()
            try:
                future.set_result(asyncio.run(coroutine))
            except BaseException as error:
                future.set_exception(error)
            return future

    bridge = WebUIBridge(Backend())
    invalid = bridge.apply_filters({"words": [], "phrases": [], "patterns": ["broken["]})
    assert not invalid["ok"]
    assert invalid["invalid_rule"] == {"category": "patterns", "index": 0}
    assert bridge.apply_filters({"words": ["alpha"], "phrases": [], "patterns": []})["ok"]
    assert not manager.filter_message("alpha")


def _test_bridge(manager: FilterManager) -> WebUIBridge:
    class Backend:
        application = SimpleNamespace(services=SimpleNamespace(filter_manager=manager))

        @staticmethod
        def submit(coroutine) -> Future:
            future: Future = Future()
            try:
                future.set_result(asyncio.run(coroutine))
            except BaseException as error:
                future.set_exception(error)
            return future

    return WebUIBridge(Backend())


def test_tester_uses_effective_session_rules_and_never_writes_files(tmp_path, monkeypatch) -> None:
    _files(tmp_path, "saved\n", "", "")
    manager = FilterManager()
    load_filters_from_directory(manager, tmp_path)
    apply_filter_settings(manager, validate_filter_input({"words": ["session"], "phrases": [], "patterns": []}))
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    snapshot = manager.snapshot()
    bridge = _test_bridge(manager)

    def unexpected_paths(*args, **kwargs):
        pytest.fail("Filter testing must not access profile files")

    monkeypatch.setattr("app.filter_settings.RuntimePaths.default", unexpected_paths)
    active = bridge.test_filters("SESSION", "active")
    assert active == {
        "ok": True, "source": "active", "decision": "BLOCK",
        "category": "words", "rule": "session", "timed_out": False,
    }
    assert bridge.test_filters("saved", "active")["decision"] == "ALLOW"
    payload = {"words": ["draft"], "phrases": [], "patterns": []}
    assert bridge.test_filters("draft", "draft", payload)["decision"] == "BLOCK"
    assert bridge.test_filters("session", "draft", payload)["decision"] == "ALLOW"
    assert bridge.test_filters("draft", "active")["decision"] == "ALLOW"
    assert manager.snapshot() == snapshot
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before


def test_draft_tester_uses_existing_normalization_and_python_validation() -> None:
    manager = FilterManager()
    manager.add_blocked_word("active")
    bridge = _test_bridge(manager)
    payload = {"words": ["", " # comment", "  alpha ", "alpha"], "phrases": [], "patterns": []}
    result = bridge.test_filters("ALPHA", "draft", payload)
    assert result["rule"] == "alpha"
    assert result["decision"] == "BLOCK"

    # VERSION1 is accepted by regex, but rejected by the established Python re contract.
    invalid = bridge.test_filters("ordinary", "draft", {
        "words": ["new"], "phrases": [], "patterns": ["# comment", "", "(?V1)pattern"],
    })
    assert not invalid["ok"]
    assert invalid["invalid_rule"] == {"category": "patterns", "index": 2}
    assert "Invalid regex" in invalid["error"]
    assert manager.snapshot() == (["active"], [], [])


@pytest.mark.parametrize(
    ("text", "source", "payload"),
    [
        (None, "active", None),
        (42, "active", None),
        ("text", "saved", None),
        ("text", "draft", None),
        ("text", "draft", {"words": [], "phrases": []}),
        ("text", "active", {"words": [], "phrases": [], "patterns": []}),
        ("text", "draft", {"words": ["bad\ufffd"], "phrases": [], "patterns": []}),
    ],
)
def test_tester_rejects_bad_requests_without_changing_active_filters(text, source, payload) -> None:
    manager = FilterManager()
    manager.add_blocked_word("active")

    result = _test_bridge(manager).test_filters(text, source, payload)

    assert not result["ok"]
    assert result["error"]
    assert "decision" not in result
    assert manager.snapshot() == (["active"], [], [])


def test_draft_tester_preserves_the_live_regex_timeout() -> None:
    manager = FilterManager()
    result = evaluate_filter_settings(manager, "a" * 20000 + "!", "draft", {
        "words": [], "phrases": [], "patterns": ["(a+)+$"],
    })

    assert result["decision"] == "BLOCK"
    assert result["category"] == "patterns"
    assert result["rule"] == "(a+)+$"
    assert result["timed_out"]
    assert manager.snapshot() == ([], [], [])


def test_tester_reports_bridge_deadline_without_a_moderation_decision(monkeypatch) -> None:
    bridge = _test_bridge(FilterManager())

    def timed_out(coroutine, **kwargs):
        coroutine.close()
        raise BridgeOperationTimedOut("test filters")

    monkeypatch.setattr(bridge, "_wait_for_backend", timed_out)

    result = bridge.test_filters("sample", "active")

    assert not result["ok"]
    assert "timed out" in result["error"]
    assert "decision" not in result
