"""Tests for shared text normalization."""

from app.utils.text import format_duration, normalize_command_name, normalize_text, parse_command


def test_normalize_text_collapses_whitespace_and_unicode() -> None:
    assert normalize_text("  hello\u00a0\u00a0world  ") == "hello world"
    assert normalize_command_name("!PING") == "ping"


def test_parse_command_preserves_argument_words() -> None:
    assert parse_command("  !ask  how are you? ", "!") == ("ask", "how are you?")
    assert parse_command("!weather\tNew York", "!") == (
        "weather",
        "New York",
    )
    assert parse_command("hello", "!") is None


def test_format_duration_is_compact() -> None:
    assert format_duration(0) == "0s"
    assert format_duration(3_661) == "1h 01m 01s"
    assert format_duration(90_061) == "1d 01h 01m"