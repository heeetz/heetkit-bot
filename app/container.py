"""Application composition root for explicit dependency wiring."""

from dataclasses import dataclass

import httpx
import logging

from config import FILTERS_DIRECTORY
from app.commands.ai import register_ai_commands
from app.commands.fun import register_fun_commands
from app.commands.info import register_info_commands, register_weather_commands
from app.commands.social import register_social_commands
from app.commands.registry import CommandDispatcher, CommandRegistry
from app.config.settings import Settings
from app.database.database import Database
from app.database.repository import AIMemoryRepository, UserRepository
from app.services.facade import ApplicationServices
from app.services.memory import AIMemoryService
from app.services.weather import OpenMeteoWeatherService
from app.services.gemini_ai_service import GeminiAIService
from app.services.filter_manager import FilterManager
from app.services.ai_request_policy import AIRequestPolicy
from app.services.twitch import TwitchAPIService
from app.runtime_state import RuntimeState
from app.utils.cooldown import CooldownManager
from app.utils.logging import get_logger
from app.utils.output_limiter import OutputLimiter


@dataclass(slots=True)
class Application:
    settings: Settings
    database: Database
    http_client: httpx.AsyncClient
    services: ApplicationServices
    registry: CommandRegistry
    dispatcher: CommandDispatcher

    async def startup(self) -> None:
        await self.database.initialize()
        # Load filter rules from files
        try:
            from app.services.filter_loader import load_filters_from_directory
            load_filters_from_directory(
                self.services.filter_manager,
                directory_path=str(FILTERS_DIRECTORY),
            )
        except Exception as e:
            # If filter loading fails, log the error and re-raise to prevent running without filters
            logger = logging.getLogger(__name__)
            logger.error("Filter loading failed: %s", str(e))
            raise

    async def shutdown(self) -> None:
        await self.http_client.aclose()
        await self.database.close()


def build_application(settings: Settings) -> Application:
    database = Database(settings.database_url)
    http_client = httpx.AsyncClient(timeout=httpx.Timeout(8.0))
    user_repository = UserRepository(database.session_factory)
    memory_repository = AIMemoryRepository(database.session_factory)
    filter_manager = FilterManager()
    ai_request_policy = AIRequestPolicy()
    twitch_api = TwitchAPIService()
    memory = AIMemoryService(memory_repository)
    runtime_state = RuntimeState()
    services = ApplicationServices(
        users=user_repository,
        memory=memory,
        ai=GeminiAIService(
            settings,
            runtime_state=runtime_state,
            filter_manager=filter_manager,
        ),
        weather=OpenMeteoWeatherService(http_client),
        filter_manager=filter_manager,
        ai_request_policy=ai_request_policy,
        settings=settings,
        runtime_state=runtime_state,
        twitch=twitch_api,
    )
    registry = CommandRegistry()
    register_fun_commands(registry)
    register_weather_commands(registry)
    register_info_commands(registry)
    register_ai_commands(registry)
    register_social_commands(registry)
    dispatcher = CommandDispatcher(
        registry=registry,
        cooldowns=CooldownManager(),
        logger=get_logger("app.commands"),
        command_prefix=settings.command_prefix,
        max_arguments_length=settings.command_max_arguments_length,
        output_limiter=OutputLimiter(),
        ai_cooldown_bypass_user_id=settings.ai_cooldown_bypass_user_id,
    )
    return Application(
        settings=settings,
        database=database,
        http_client=http_client,
        services=services,
        registry=registry,
        dispatcher=dispatcher,
    )
