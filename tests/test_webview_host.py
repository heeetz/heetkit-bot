"""Tests for the desktop host bridge without opening a native window."""

from types import SimpleNamespace
from typing import cast

import pytest

from app.webview_host import AsyncioBackendHost, WebUIBridge, resolve_frontend_url


def test_bridge_reads_shared_runtime_status() -> None:
    runtime_state = SimpleNamespace(status=lambda: (True, 42))
    application = SimpleNamespace(
        services=SimpleNamespace(runtime_state=runtime_state),
        settings=SimpleNamespace(twitch_channel="channel", twitch_bot_username="bot"),
    )
    backend = SimpleNamespace(application=application)

    result = WebUIBridge(cast(AsyncioBackendHost, backend)).get_app_status()

    assert result == {
        "running": True,
        "uptime_seconds": 42,
        "channel": "channel",
        "account": "bot",
    }


def test_production_frontend_requires_a_built_entrypoint(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.webview_host.FRONTEND_ENTRYPOINT",
        SimpleNamespace(is_file=lambda: False),
    )

    with pytest.raises(FileNotFoundError, match="npm run build"):
        resolve_frontend_url(None)


def test_development_frontend_url_does_not_require_build() -> None:
    assert resolve_frontend_url("http://localhost:5173") == "http://localhost:5173"
