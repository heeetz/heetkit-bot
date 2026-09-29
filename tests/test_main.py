"""Tests for the canonical desktop application entry point."""

from app.main import main


def test_main_delegates_to_the_web_desktop_host(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr("app.main.webview_main", lambda: calls.append("webview"))

    main()

    assert calls == ["webview"]
