"""Failure isolation for optional global message filters."""

import logging
import re
from pathlib import Path

import pytest

from app.services.filter_loader import load_filters_from_directory
from app.services.filter_manager import FilterManager


def test_bad_regex_and_corrupt_lines_keep_other_rules(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    (tmp_path / "blocked_words.txt").write_bytes(b"alpha\n\xff\nbeta\n")
    (tmp_path / "blocked_phrases.txt").write_text("free followers\n", encoding="utf-8")
    (tmp_path / "blocked_patterns.txt").write_text("broken[\nhttp://bad\\.site\n", encoding="utf-8")
    manager = FilterManager()

    with caplog.at_level(logging.WARNING):
        load_filters_from_directory(manager, str(tmp_path))

    for message in ("alpha", "beta", "Get FREE FOLLOWERS", "http://bad.site"):
        assert not manager.filter_message(message)
    assert manager.filter_message("ordinary chat")
    assert "Invalid UTF-8" in caplog.text
    assert "blocked_words.txt line 2" in caplog.text
    assert "Invalid regex" in caplog.text
    assert "blocked_patterns.txt line 1" in caplog.text


def test_unreadable_file_keeps_its_prior_rules_and_other_files_reload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    words = tmp_path / "blocked_words.txt"
    phrases = tmp_path / "blocked_phrases.txt"
    words.write_text("original\n", encoding="utf-8")
    phrases.write_text("old phrase\n", encoding="utf-8")
    manager = FilterManager()
    load_filters_from_directory(manager, str(tmp_path))
    phrases.write_text("new phrase\n", encoding="utf-8")
    original_open = Path.open

    def fail_words(self: Path, *args, **kwargs):
        if self == words:
            raise PermissionError("denied")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_words)
    with caplog.at_level(logging.ERROR):
        load_filters_from_directory(manager, str(tmp_path))

    assert not manager.filter_message("original")
    assert not manager.filter_message("new phrase")
    assert manager.filter_message("old phrase")
    assert "Cannot load filter file" in caplog.text
    assert "keeping existing rules" in caplog.text


def test_missing_file_preserves_rules_on_reload(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    words = tmp_path / "blocked_words.txt"
    words.write_text("original\n", encoding="utf-8")
    manager = FilterManager()
    load_filters_from_directory(manager, str(tmp_path))
    words.unlink()

    with caplog.at_level(logging.WARNING):
        load_filters_from_directory(manager, str(tmp_path))

    assert not manager.filter_message("original")
    assert not words.exists()
    assert "is missing" in caplog.text


def test_invalid_pattern_is_rejected_when_added_directly() -> None:
    manager = FilterManager()
    with pytest.raises(re.error):
        manager.add_blocked_pattern("broken[")
    manager.add_blocked_pattern("valid", is_regex=False)
    assert not manager.filter_message("valid")


def test_invalid_only_reload_does_not_clear_last_valid_patterns(tmp_path: Path) -> None:
    patterns = tmp_path / "blocked_patterns.txt"
    patterns.write_text("original\\d+\n", encoding="utf-8")
    manager = FilterManager()
    load_filters_from_directory(manager, str(tmp_path))
    patterns.write_text("broken[\n", encoding="utf-8")

    load_filters_from_directory(manager, str(tmp_path))

    assert not manager.filter_message("original123")
