"""Application composition root for explicit dependency wiring."""

from dataclasses import dataclass

import httpx
import logging

from config import COMMAND_SETTINGS_PATH, FILTERS_DIRECTORY, PERSONALITY_SETTINGS_PATH
from app.commands.ai import register_ai_commands
from app.commands.fun import register_fun_commands
from app.commands.info import register_info_commands, register_weather_commands
from app.commands.social import register_social_commands
from app.commands.registry import CommandDispatcher, CommandRegistry
from app.custom_commands import CustomCommandStore
from app.message_triggers import MessageTriggerStore
from app.runtime_paths import RuntimePaths
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
    ai_service: GeminiAIService
    services: ApplicationServices
    registry: CommandRegistry
    dispatcher: CommandDispatcher
    custom_commands: CustomCommandStore | None = None

    async def startup(self) -> None:
        await self.database.initialize()
        # Optional filter files should not prevent the rest of the app from starting.
        try:
            from app.services.filter_loader import load_filters_from_directory
            load_filters_from_directory(
                self.services.filter_manager,
                directory_path=str(FILTERS_DIRECTORY),
            )
        except Exception:
            logger = logging.getLogger(__name__)
            logger.exception("Filter loading failed unexpectedly; existing rules remain active")

    async def shutdown(self) -> None:
        try:
            await self.ai_service.aclose()
        finally:
            try:
                await self.http_client.aclose()
            finally:
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
    runtime_state = RuntimeState(
        command_settings_path=COMMAND_SETTINGS_PATH,
        personality_settings_path=PERSONALITY_SETTINGS_PATH,
    )
    ai_service = GeminiAIService(
        settings,
        runtime_state=runtime_state,
        filter_manager=filter_manager,
    )
    services = ApplicationServices(
        users=user_repository,
        memory=memory,
        ai=ai_service,
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
    runtime_state.configure_commands(registry.definitions())
    custom_commands = CustomCommandStore(
        RuntimePaths.default().custom_commands,
        {name for definition in registry.definitions() for name in (definition.name, *definition.aliases)},
    )
    message_triggers = MessageTriggerStore(RuntimePaths.default().message_triggers)
    dispatcher = CommandDispatcher(
        registry=registry,
        cooldowns=CooldownManager(),
        logger=get_logger("app.commands"),
        command_prefix=settings.command_prefix,
        max_arguments_length=settings.command_max_arguments_length,
        output_limiter=OutputLimiter(),
        ai_cooldown_bypass_user_id=settings.ai_cooldown_bypass_user_id,
        runtime_state=runtime_state,
        custom_commands=custom_commands,
        message_triggers=message_triggers,
    )
    return Application(
        settings=settings,
        database=database,
        http_client=http_client,
        ai_service=ai_service,
        services=services,
        registry=registry,
        custom_commands=custom_commands,
        dispatcher=dispatcher,
    )
