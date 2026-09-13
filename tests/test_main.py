"""Tests for process-level application failure handling."""

import sys

import pytest

from app.main import main
from app.twitch.client import TwitchConnectionError


def test_main_exits_cleanly_for_twitch_connection_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_connection_error(coroutine) -> None:
        coroutine.close()
        raise TwitchConnectionError("Twitch user token validation failed.")

    monkeypatch.setattr("app.main.asyncio.run", raise_connection_error)
    monkeypatch.setattr(sys, "argv", ["twitch-bot"])

    with pytest.raises(SystemExit) as error:
        main()

    assert error.value.code == 1