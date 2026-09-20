"""Service bundle injected into command execution."""

from dataclasses import dataclass

from app.services.contracts import AIService, WeatherService
from app.services.user_service import UserService
from app.services.memory import AIMemoryService
from app.services.filter_manager import FilterManager
from app.services.ai_request_policy import AIRequestPolicy
from app.config.settings import Settings
from app.runtime_state import RuntimeState
from app.services.twitch import TwitchAPIService


@dataclass(frozen=True, slots=True)
class ApplicationServices:
    users: UserService
    ai: AIService
    weather: WeatherService
    filter_manager: FilterManager
    ai_request_policy: AIRequestPolicy
    settings: Settings
    runtime_state: RuntimeState | None = None
    memory: AIMemoryService | None = None
    twitch: TwitchAPIService | None = None
