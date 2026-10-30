"""Application composition root for explicit dependency wiring."""

from dataclasses import dataclass, field

import httpx
import logging

from app.commands.ai import register_ai_commands
from app.commands.fun import register_fun_commands
from app.commands.info import register_info_commands, register_weather_commands
from app.commands.social import register_social_commands
from app.commands.registry import CommandDispatcher, CommandRegistry
from app.custom_commands import CustomCommandStore
from app.announcements import AnnouncementStore, AnnouncementScheduler
from app.ai_user_blocks import AIUserBlocklist
from app.command_restrictions import CommandRestrictionStore
from app.message_triggers import MessageTriggerStore
from app.runtime_paths import RuntimePaths
from app.fun_settings import FunSettingsStore
from app.config.settings import Settings
from app.database.database import Database
from app.database.repository import AIMemoryRepository, UserRepository
from app.analytics import Analytics
from app.services.facade import ApplicationServices
from app.services.memory import AIMemoryService
from app.services.weather import OpenMeteoWeatherService
from app.services.ai_service import SharedAIService
from app.services.ai_playground import AIPlayground
from app.services.filter_manager import FilterManager
from app.services.ai_request_policy import AIRequestPolicy
from app.services.twitch import TwitchAPIService
from app.runtime_state import RuntimeState
from app.utils.cooldown import CooldownManager
from app.utils.logging import get_logger


@dataclass(slots=True)
class Application:
    settings: Settings
    database: Database
    http_client: httpx.AsyncClient
    ai_service: SharedAIService
    services: ApplicationServices
    registry: CommandRegistry
    dispatcher: CommandDispatcher
    custom_commands: CustomCommandStore | None = None
    fun_settings: FunSettingsStore | None = None
    announcements: AnnouncementStore | None = None
    ai_playground: AIPlayground = field(init=False)
    ai_balance: object | None = field(init=False, default=None)
    announcement_scheduler: AnnouncementScheduler | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        self.ai_playground = AIPlayground(self.settings, self.services)
        if self.announcements is not None:
            self.announcement_scheduler = AnnouncementScheduler(self.announcements,
                self.services.twitch, self.settings, self.services.runtime_state)

    async def startup(self) -> None:
        await self.database.initialize()
        if getattr(self.services, "analytics", None) is not None:
            await self.services.analytics.start()
        # Optional filter files should not prevent the rest of the app from starting.
        try:
            from app.services.filter_loader import load_filters_from_directory
            load_filters_from_directory(
                self.services.filter_manager,
                directory_path=str(RuntimePaths.default().filters),
            )
        except Exception:
            logger = logging.getLogger(__name__)
            logger.exception("Filter loading failed unexpectedly; existing rules remain active")
        if self.announcement_scheduler is not None:
            self.announcement_scheduler.start()

    async def shutdown(self) -> None:
        try:
            try:
                try:
                    if self.announcement_scheduler is not None:
                        await self.announcement_scheduler.close()
                finally:
                    try:
                        await self.ai_playground.close()
                    finally:
                        if self.ai_balance is not None:
                            await self.ai_balance.aclose()
            finally:
                await self.ai_service.aclose()
        finally:
            try:
                await self.http_client.aclose()
            finally:
                try:
                    if getattr(self.services, "analytics", None) is not None:
                        await self.services.analytics.close()
                finally:
                    await self.database.close()


def build_application(settings: Settings) -> Application:
    paths = RuntimePaths.default()
    database = Database(settings.database_url, history_limit=settings.ai_history_max_entries,
                        context_limit=settings.ai_context_max_entries)
    http_client = httpx.AsyncClient(timeout=httpx.Timeout(8.0))
    user_repository = UserRepository(database.session_factory)
    analytics = Analytics(database.path.with_name(database.path.name + ".analytics.sqlite3") if database.path else None)
    user_repository.analytics = analytics
    memory_repository = AIMemoryRepository(database.session_factory)
    filter_manager = FilterManager()
    ai_request_policy = AIRequestPolicy()
    twitch_api = TwitchAPIService()
    twitch_api.analytics = analytics
    memory = AIMemoryService(memory_repository)
    runtime_state = RuntimeState(
        command_settings_path=paths.command_settings,
        personality_settings_path=paths.personality_settings,
    )
    ai_service = SharedAIService(
        settings,
        runtime_state=runtime_state,
        filter_manager=filter_manager,
    )
    registry = CommandRegistry()
    fun_settings = FunSettingsStore(paths.config / "fun_settings.json")
    register_fun_commands(registry, fun_settings)
    register_weather_commands(registry)
    register_info_commands(registry)
    register_ai_commands(registry)
    register_social_commands(registry)
    runtime_state.configure_commands(registry.definitions())
    custom_commands = CustomCommandStore(
        paths.custom_commands,
        {name for definition in registry.definitions() for name in (definition.name, *definition.aliases)},
        namespace_lock=runtime_state.command_namespace_lock,
    )
    runtime_state.bind_custom_commands(custom_commands)
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
        ai_user_blocks=AIUserBlocklist(paths.config / "ai_user_blocks.json"),
        custom_commands=custom_commands,
        command_restrictions=CommandRestrictionStore(paths.config / "command_restrictions.json"),
        analytics=analytics,
    )
    services.command_restrictions.migrate_ai_blocks(services.ai_user_blocks, settings.twitch_channel_user_id)
    message_triggers = MessageTriggerStore(paths.message_triggers)
    dispatcher = CommandDispatcher(
        registry=registry,
        cooldowns=CooldownManager(),
        logger=get_logger("app.commands"),
        command_prefix=settings.command_prefix,
        max_arguments_length=settings.command_max_arguments_length,
        output_limiter=twitch_api.output_limiter,
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
        fun_settings=fun_settings,
        announcements=AnnouncementStore(paths.config / "announcements.json"),
    )
