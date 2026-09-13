"""Current weather lookup through Open-Meteo's public APIs."""

import re
from difflib import SequenceMatcher
from typing import Literal

import httpx

from app.services.contracts import WeatherReport
from app.utils.text import normalize_text


class WeatherServiceError(RuntimeError):
    """The weather provider could not complete a request."""


WeatherLanguage = Literal["en", "ru", "uk"]

WMO_CONDITIONS = {
    0: "clear",
    1: "mostly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "foggy",
    48: "foggy",
    51: "drizzle",
    53: "drizzle",
    55: "drizzle",
    61: "rain",
    63: "rain",
    65: "heavy rain",
    71: "snow",
    73: "snow",
    75: "heavy snow",
    80: "showers",
    81: "showers",
    82: "heavy showers",
    95: "thunderstorm",
    96: "thunderstorm",
    99: "thunderstorm",
}

LOCALIZED_CONDITIONS: dict[str, dict[WeatherLanguage, str]] = {
    "clear": {"en": "clear", "ru": "ясно", "uk": "ясно"},
    "mostly clear": {"en": "mostly clear", "ru": "преимущественно ясно", "uk": "переважно ясно"},
    "partly cloudy": {"en": "partly cloudy", "ru": "переменная облачность", "uk": "мінлива хмарність"},
    "overcast": {"en": "overcast", "ru": "облачно", "uk": "хмарно"},
    "foggy": {"en": "foggy", "ru": "туман", "uk": "туман"},
    "drizzle": {"en": "drizzle", "ru": "морось", "uk": "мряка"},
    "rain": {"en": "rain", "ru": "дождь", "uk": "дощ"},
    "heavy rain": {"en": "heavy rain", "ru": "сильный дождь", "uk": "сильний дощ"},
    "snow": {"en": "snow", "ru": "снег", "uk": "сніг"},
    "heavy snow": {"en": "heavy snow", "ru": "сильный снег", "uk": "сильний сніг"},
    "showers": {"en": "showers", "ru": "ливни", "uk": "зливи"},
    "heavy showers": {"en": "heavy showers", "ru": "сильные ливни", "uk": "сильні зливи"},
    "thunderstorm": {"en": "thunderstorm", "ru": "гроза", "uk": "гроза"},
    "unknown conditions": {"en": "unknown conditions", "ru": "неизвестно", "uk": "невідомо"},
}

_CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")
_UKRAINIAN_RE = re.compile(r"[іїєґІЇЄҐ]")
_LOCATION_TOKEN_RE = re.compile(r"[\w]+", re.UNICODE)


def weather_language_for_query(query: str) -> WeatherLanguage:
    """Detect the response language from the query's script and spelling."""

    if _UKRAINIAN_RE.search(query):
        return "uk"
    if _CYRILLIC_RE.search(query):
        return "ru"
    return "en"


def geocoding_language_for_query(query: str) -> WeatherLanguage:
    """Choose the preferred Open-Meteo language for the query."""

    return weather_language_for_query(query)


def _other_geocoding_language(language: WeatherLanguage) -> WeatherLanguage:
    return "en" if language in {"ru", "uk"} else "ru"


def _location_tokens(value: str) -> set[str]:
    return {token.casefold() for token in _LOCATION_TOKEN_RE.findall(value)}


def _location_match_score(query: str, location: dict) -> tuple[int, int]:
    query_normalized = normalize_text(query).casefold()
    query_tokens = _location_tokens(query)
    name = normalize_text(str(location.get("name", "")))
    name_tokens = _location_tokens(name)
    candidate_text = " ".join(
        str(location.get(field, ""))
        for field in ("name", "country", "country_code", "admin1", "admin2")
    )
    candidate_tokens = _location_tokens(candidate_text)

    score = sum(5 for token in query_tokens if token in name_tokens)
    score += sum(2 for token in query_tokens if token in candidate_tokens and token not in name_tokens)
    if name_tokens and query_tokens:
        score += round(
            8
            * max(
                SequenceMatcher(None, name.casefold(), token).ratio()
                for token in query_tokens
            )
        )
    if name.casefold() == query_normalized:
        score += 20
    if query_tokens and query_tokens <= candidate_tokens:
        score += 10

    population = int(location.get("population") or 0)
    return score, population


def _localized_condition(condition: str, language: WeatherLanguage) -> str:
    return LOCALIZED_CONDITIONS.get(condition, LOCALIZED_CONDITIONS["unknown conditions"])[language]


def format_weather_response(report: WeatherReport, query: str) -> str:
    """Format the concise weather response in the query's language."""

    language = weather_language_for_query(query)
    condition = _localized_condition(report.condition, language)
    if language == "en":
        return f"{report.city}: {report.temperature_celsius:g}°C, {condition}, wind {report.wind_speed_kmh:g} km/h."

    wind_unit = "км/ч" if language == "ru" else "км/год"
    wind_label = "ветер" if language == "ru" else "вітер"
    return (
        f"{report.city}: {report.temperature_celsius:+g}°C, "
        f"{condition}, {wind_label} {report.wind_speed_kmh:g} {wind_unit}."
    )


class OpenMeteoWeatherService:
    geocoding_url = "https://geocoding-api.open-meteo.com/v1/search"
    forecast_url = "https://api.open-meteo.com/v1/forecast"

    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self._http_client = http_client

    async def get_current_weather(self, city: str) -> WeatherReport | None:
        query = normalize_text(city)
        try:
            preferred_language = geocoding_language_for_query(query)
            location = await self._geocode(query, preferred_language)
            if location is None:
                location = await self._geocode(query, _other_geocoding_language(preferred_language))
            if location is None:
                return None
            weather_response = await self._http_client.get(
                self.forecast_url,
                params={
                    "latitude": location["latitude"],
                    "longitude": location["longitude"],
                    "current": "temperature_2m,weather_code,wind_speed_10m",
                    "temperature_unit": "celsius",
                    "wind_speed_unit": "kmh",
                },
            )
            weather_response.raise_for_status()
            current = weather_response.json()["current"]
            return WeatherReport(
                city=location["name"],
                temperature_celsius=float(current["temperature_2m"]),
                condition=WMO_CONDITIONS.get(int(current["weather_code"]), "unknown conditions"),
                wind_speed_kmh=float(current["wind_speed_10m"]),
            )
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
            raise WeatherServiceError("Weather provider request failed.") from error

    async def _geocode(self, query: str, language: WeatherLanguage) -> dict | None:
        geocoding_response = await self._http_client.get(
            self.geocoding_url,
            params={"name": query, "count": 10, "language": language, "format": "json"},
        )
        geocoding_response.raise_for_status()
        results = geocoding_response.json().get("results", [])
        if not results:
            return None
        return max(results, key=lambda location: _location_match_score(query, location))