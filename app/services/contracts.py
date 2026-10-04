"""Replaceable service contracts used by command handlers."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class AIReply:
    text: str
    is_available: bool


class AIService(Protocol):
    @property
    def is_available(self) -> bool: ...

    async def generate_reply(
        self,
        prompt: str,
        user_id: str,
        memory_context: str | None = None,
        stream_category: str | None = None,
    ) -> AIReply: ...


@dataclass(frozen=True, slots=True)
class AIMemoryExchange:
    request_text: str
    response_text: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class WeatherReport:
    city: str
    temperature_celsius: float
    condition: str
    wind_speed_kmh: float


class WeatherService(Protocol):
    async def get_current_weather(self, city: str) -> WeatherReport | None: ...
