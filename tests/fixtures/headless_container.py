"""Synthetic Linux container probe. Never shipped in the production image."""

import asyncio
import importlib.util
import json
import logging
import os
from pathlib import Path
import sqlite3
import stat
import sys

sys.path.insert(0, "/opt/heetkit")

from app import bot_runtime, headless
from app.runtime_paths import RuntimePaths, prepare_runtime_data
from app.twitch.client import TwitchChatBot
from app.app_settings import AppSettingsStore
from app.operation_policy import OperationPolicy
from app.services.twitch import TwitchAPIService


paths = RuntimePaths.default()


def seed():
    assert sys.platform == "linux" and os.getuid() == 10001
    assert paths.root == Path("/var/lib/heetkit")
    for package in ("keyring", "webview", "pystray", "PIL", "PyInstaller"):
        assert importlib.util.find_spec(package) is None, package
    frontend = Path("/opt/heetkit/app/resources/frontend")
    assert (frontend / "index.html").is_file()
    assert any((frontend / "assets").glob("*.js"))
    assert any((frontend / "assets").glob("*.css"))
    for asset in frontend.rglob("*"):
        if asset.is_file():
            relative = asset.relative_to(frontend)
            assert relative.as_posix() in ("index.html", "icon.png") or (
                relative.parent == Path("assets") and relative.suffix in (".js", ".css")
            ), "Unexpected frontend output: " + str(relative)
            assert b"synthetic-excluded-build-context-sentinel" not in asset.read_bytes(), str(relative)
    for name in ("data", "resources/private.json", "resources/icon.png", "resources/icon.ico", "resources/icon.icns", "resources/tray.png"):
        assert not Path("/opt/heetkit/app", name).exists(), "Excluded image content: " + name
    assert not any(Path("/opt/heetkit", name).exists() for name in (".git", "data", "frontend", "tests", "build", ".env"))
    prepare_runtime_data(str(paths.tokens), "sqlite+aiosqlite:///" + str(paths.database))
    paths.app_settings.write_text(json.dumps({"version": 1, "twitch": {
        "client_id": "synthetic-client", "bot_user_id": "100", "bot_username": "syntheticbot",
        "channel_user_id": "200", "channel": "syntheticchannel"}, "ai": {
        "memory_enabled": False, "selected_model": "gemini-synthetic",
        "fallback_model": "gemini-synthetic-fallback"}}))
    paths.personality_settings.write_text(json.dumps({"active_personality": "neutral", "overrides": {"neutral": "Synthetic saved personality."}, "profile_instructions": ""}))
    (paths.filters / "blocked_words.txt").write_text("syntheticblocked\n")
    paths.tokens.write_text(json.dumps({"100": {"user_id": "100", "token": "synthetic-access", "refresh": "synthetic-refresh-0"}}))
    paths.tokens.chmod(0o600)
    fifo = Path("/tmp/probe-secret-fifo")
    os.mkfifo(fifo)
    original = os.environ["TWITCH_CLIENT_SECRET_FILE"]
    try:
        os.environ["TWITCH_CLIENT_SECRET_FILE"] = str(fifo)
        try:
            headless.secret_file_settings()
        except headless.HeadlessError:
            pass
        else:
            raise AssertionError("FIFO secret accepted")
    finally:
        os.environ["TWITCH_CLIENT_SECRET_FILE"] = original
        fifo.unlink()


async def session(**kwargs):
    # Keep Application, BotRuntime, SQLite, stores, token loading/saving and signal
    # handling real. Replace only Twitch's remote boundary; the container also has
    # --network=none, and both HTTP libraries reject any accidental request.
    import aiohttp
    import httpx

    async def forbidden(*args, **options):
        raise AssertionError("Network access in synthetic container validation")

    aiohttp.ClientSession._request = forbidden
    httpx.AsyncClient.send = forbidden
    settings, services = kwargs["settings"], kwargs["services"]
    assert kwargs["headless"]
    assert settings.twitch_client_id == "synthetic-client"
    assert settings.twitch_channel == "syntheticchannel"
    assert settings.gemini_model == "gemini-synthetic", "Saved model pair was not applied"
    assert settings.gemini_fallback_model == "gemini-synthetic-fallback"
    assert settings.twitch_client_secret.get_secret_value() == "synthetic-client-secret"
    assert "TWITCH_CLIENT_SECRET" not in os.environ
    assert not services.runtime_state.ai_memory_enabled
    assert services.runtime_state.get_ai_personality_prompt("neutral") == "Synthetic saved personality."
    assert not services.filter_manager.filter_message("syntheticblocked")
    counter = paths.data / "probe-starts"
    previous = int(counter.read_text()) if counter.exists() else 0
    if previous:
        assert await services.users.get_by_twitch_user_id("300") is not None
    await services.users.upsert_seen(twitch_user_id="300", username="syntheticviewer")
    bot = TwitchChatBot(settings, settings.primary_account, services, kwargs["dispatcher"], logging.getLogger("probe"))

    async def validate_and_rotate(token, refresh):
        assert refresh == f"synthetic-refresh-{previous}"
        bot._http._tokens["100"] = {"user_id": "100", "token": token, "refresh": f"synthetic-refresh-{previous + 1}", "last_validated": "2026-10-18T00:00:00"}

    bot.add_token = validate_and_rotate
    await bot.load_tokens()
    counter.write_text(str(previous + 1))
    services.runtime_state.set_twitch_connection_state("connected")
    try:
        await kwargs["stop_event"].wait()
    finally:
        await bot.close()
        (paths.data / "probe-stops").write_text(str(previous + 1))


def verify():
    starts = int((paths.data / "probe-starts").read_text())
    assert starts == 3
    assert (paths.data / "probe-stops").read_text() == "3"
    assert json.loads(paths.tokens.read_text())["100"]["refresh"] == "synthetic-refresh-3"
    assert stat.S_IMODE(paths.tokens.stat().st_mode) == 0o600
    assert not Path("/tmp/heetkit-health.json").exists()
    with sqlite3.connect(paths.database) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    assert "keyring" not in sys.modules
    print(f"Linux uid={os.getuid()}: signals, restart/recreation, SQLite, profile loading and token rotation passed ({starts} sessions).")


def policy_probe(arguments):
    """Fixed commands over disposable synthetic probe state, never production UI."""
    if arguments[0] == "set-mode":
        AppSettingsStore(paths.app_settings).update_operation_mode(arguments[1])
    elif arguments[0] == "set-live":
        assert arguments[1] in {"true", "false", "unknown"}
        (paths.data / "probe-live").write_text(arguments[1])
    elif arguments[0] == "stats":
        def counter(name):
            path = paths.data / name
            return int(path.read_text()) if path.exists() else 0
        print(json.dumps({"mode": AppSettingsStore(paths.app_settings).snapshot().startup.operation_mode,
            "starts": counter("probe-starts"), "stops": counter("probe-stops")}))
    else:
        raise AssertionError("Unknown probe command")


async def synthetic_live(service, settings):
    path = paths.data / "probe-live"
    value = path.read_text() if path.exists() else "false"
    if value == "unknown":
        raise OSError("Synthetic monitoring interruption")
    return value == "true"


def synthetic_policy(runtime, store):
    return OperationPolicy(runtime, store, poll_interval=0.1, max_backoff=0.4, request_timeout=1)


if __name__ == "__main__":
    os.umask(0o077)
    if sys.argv[1] == "seed":
        seed()
    elif sys.argv[1] == "verify":
        verify()
    elif sys.argv[1] == "policy":
        policy_probe(sys.argv[2:])
    else:
        # Block network before application/monitor startup, even while chat is off.
        import aiohttp
        import httpx
        async def forbidden(*args, **kwargs):
            raise AssertionError("Network access in synthetic container validation")
        aiohttp.ClientSession._request = forbidden
        httpx.AsyncClient.send = forbidden
        TwitchAPIService.get_broadcaster_live = synthetic_live
        headless.OperationPolicy = synthetic_policy
        bot_runtime.run_twitch_bot = session
        raise SystemExit(headless.main(["--health-file", "/tmp/heetkit-health.json"]))
