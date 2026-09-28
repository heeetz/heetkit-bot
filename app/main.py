"""Application entry point."""

import argparse
import asyncio

from pydantic import ValidationError

from app.bot_runtime import BotRuntime
from app.config.settings import load_settings
from app.container import build_application
from app.control_panel import ControlPanel
from app.twitch.client import TwitchConnectionError
from app.utils.logging import configure_logging, get_logger


async def run(check_only: bool = False) -> None:
    settings = load_settings()
    configure_logging(settings.log_level)
    logger = get_logger("app")
    application = build_application(settings)
    bot_runtime = BotRuntime(application, get_logger("app.twitch"))
    loop = asyncio.get_running_loop()
    control_panel = None if check_only else ControlPanel(
        application.services.runtime_state,
        on_stop=lambda: loop.call_soon_threadsafe(bot_runtime.request_stop),
    )
    if control_panel is not None:
        control_panel.start()
    logger.info("Starting Twitch bot application")
    try:
        await bot_runtime.startup()
        if check_only:
            logger.info("Application health check completed")
            return
        await bot_runtime.start_bot()
        await bot_runtime.wait_until_stopped()
    except asyncio.CancelledError:
        logger.info("Application shutdown requested")
        raise
    except Exception as error:
        logger.error(
            "Application terminated because of an unrecoverable error type=%s",
            type(error).__name__,
        )
        raise
    finally:
        if control_panel is not None:
            control_panel.stop()
        await bot_runtime.shutdown()
        logger.info("Twitch bot application stopped")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Twitch bot foundation.")
    parser.add_argument("--check", action="store_true", help="Validate configuration and database startup.")
    arguments = parser.parse_args()
    try:
        asyncio.run(run(check_only=arguments.check))
    except ValidationError as error:
        parser.error(f"Invalid configuration: {error}")
    except TwitchConnectionError:
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
