"""Real private API/static server for browser tests; synthetic profile, no Twitch."""

import asyncio
import logging
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.bot_runtime import BotRuntime
from app.app_settings import AppSettingsStore
from app.config.settings import Settings
from app.container import build_application
from app.management_api import ManagementAPI, ManagementConfig
from app.runtime_paths import RuntimePaths, prepare_runtime_data
from app.utils.logging import RecentLogBuffer


async def main():
    # This helper deliberately accepts no real credentials or provider access.
    for name in Settings.model_fields:
        os.environ.pop(name.upper(), None)
    os.environ["HEETKIT_DATA_DIR"] = sys.argv[1]
    paths = RuntimePaths.default()
    value = Settings(_env_file=None, twitch_client_id="synthetic-client",
        twitch_client_secret="synthetic-client-secret", gemini_api_key=None,
        twitch_bot_username="syntheticbot", twitch_bot_user_id="100",
        twitch_channel="syntheticchannel", twitch_channel_user_id="200",
        twitch_token_file=str(paths.tokens), database_url="sqlite+aiosqlite:///" + str(paths.database))
    prepare_runtime_data(value.twitch_token_file, value.database_url)
    store = AppSettingsStore(paths.app_settings)
    if not paths.app_settings.exists():
        store.update_operation_mode("manual")
    application = build_application(value)
    async def no_network(*args, **kwargs):
        raise AssertionError("External network is forbidden in browser tests")
    application.http_client.send = no_network
    async def synthetic_session(**kwargs):
        kwargs["services"].runtime_state.set_twitch_connection_state("connected")
        await kwargs["stop_event"].wait()
    import app.bot_runtime
    app.bot_runtime.run_twitch_bot = synthetic_session
    async def synthetic_live(settings):
        return False
    application.services.twitch.get_broadcaster_live = synthetic_live
    runtime = BotRuntime(application, logging.getLogger("browser-test"), headless=True)
    server = ManagementAPI(runtime, ManagementConfig("synthetic_management_token_" + "x" * 32,
        host=sys.argv[3], port=int(sys.argv[2]), allowed_host=f"{sys.argv[3]}:{sys.argv[2]}"), RecentLogBuffer())
    try:
        await runtime.startup()
        await server.start()
        print("SYNTHETIC_MANAGEMENT_READY", flush=True)
        await asyncio.Event().wait()
    finally:
        await server.close()
        await runtime.shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
