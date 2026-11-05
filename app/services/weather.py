"""Current weather lookup through Open-Meteo's public APIs."""

import asyncio
import math
import re
import unicodedata
from email.utils import parsedate_to_datetime
from time import monotonic, time
from typing import Literal

import httpx

from app.services.contracts import WeatherReport
from app.services.weather_countries import COUNTRY_LABELS
from app.utils.text import normalize_text


class WeatherServiceError(RuntimeError):
    """The weather provider could not complete a request."""

    def __init__(self, message: str, *, reason: str = "provider_failure") -> None:
        super().__init__(message)
        self.reason = reason


class WeatherLocationError(ValueError):
    """A location query cannot produce a forecast."""

    def __init__(self, reason: Literal["empty_query", "invalid_query", "qualifier_mismatch"]) -> None:
        super().__init__(reason)
        self.reason = reason


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
_REQUEST_TIMEOUT_SECONDS = 2.0
_LOOKUP_TIMEOUT_SECONDS = 12.0
_RESULT_LIMIT = 10
_SETTLEMENTS = {"PPL", "PPLC", "PPLA", "PPLA2", "PPLA3", "PPLA4", "PPLA5", "PPLF", "PPLG", "PPLL", "PPLR"}


def weather_language_for_query(query: str) -> WeatherLanguage:
    """Presentation hint only: shared Cyrillic spelling cannot identify a language."""

    if _UKRAINIAN_RE.search(query):
        return "uk"
    if _CYRILLIC_RE.search(query):
        return "ru"
    return "en"


def geocoding_language_for_query(query: str) -> WeatherLanguage:
    """Choose the preferred Open-Meteo language for the query."""

    return weather_language_for_query(query)


def _languages(query: str) -> tuple[WeatherLanguage, ...]:
    preferred = geocoding_language_for_query(query)
    return (preferred, *(lang for lang in ("uk", "ru", "en") if lang != preferred))


def _location_key(value: str) -> str:
    # Compare accents/apostrophe typography without transliterating or deleting letters.
    value = normalize_text(value).casefold().translate(str.maketrans("’ʼ‐‑", "''--"))
    folded = []
    latin = False
    for character in unicodedata.normalize("NFD", value):
        if not unicodedata.combining(character):
            latin = "LATIN" in unicodedata.name(character, "")
        if not (latin and unicodedata.combining(character)):
            folded.append(character)
    return unicodedata.normalize("NFC", "".join(folded))


_COUNTRY_CODES = {
    _location_key(label.replace(" & ", " and ")): code
    for code, labels in COUNTRY_LABELS.items()
    for label in (code, *labels)
}
_COUNTRY_CODES.update({"usa": "US", "united states of america": "US", "czech republic": "CZ", "turkey": "TR"})
_MAX_COUNTRY_WORDS = max(len(label.split()) for label in _COUNTRY_CODES)


def _country_code(name: str) -> str | None:
    return _COUNTRY_CODES.get(_location_key(name).replace(" & ", " and "))


def _country_suffix(query: str) -> tuple[str, str] | None:
    # Recognize only known suffixes, longest first. There are no remote split probes.
    words = query.rsplit(" ", _MAX_COUNTRY_WORDS)
    for start in range(1, len(words)):
        if country := _country_code(" ".join(words[start:])):
            return " ".join(words[:start]), country
    return None


def _retry_after(value: str) -> float:
    value = value.strip()
    try:
        if value.isascii() and value.isdecimal():
            delay = float(value)
            return delay if math.isfinite(delay) else 0.0
        date = parsedate_to_datetime(value)
        return max(0.0, date.timestamp() - time()) if date.tzinfo is not None else 0.0
    except (ValueError, TypeError, OverflowError, OSError):
        return 0.0


def _number(value: object, minimum: float = -math.inf, maximum: float = math.inf) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Expected a provider number")
    number = float(value)
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ValueError("Invalid provider number")
    return number


def _localized_condition(condition: str, language: WeatherLanguage) -> str:
    return LOCALIZED_CONDITIONS.get(condition, LOCALIZED_CONDITIONS["unknown conditions"])[language]


def format_weather_response(report: WeatherReport, query: str) -> str:
    """Format the concise weather response in the query's language."""

    language = report.language or weather_language_for_query(query)
    condition = _localized_condition(report.condition, language)
    location = f"{report.city}, {report.country}" if report.country else report.city
    if language == "en":
        return f"{location}: {report.temperature_celsius:g}°C, {condition}, wind {report.wind_speed_kmh:g} km/h."

    wind_unit = "км/ч" if language == "ru" else "км/год"
    wind_label = "ветер" if language == "ru" else "вітер"
    return (
        f"{location}: {report.temperature_celsius:+g}°C, "
        f"{condition}, {wind_label} {report.wind_speed_kmh:g} {wind_unit}."
    )


class OpenMeteoWeatherService:
    geocoding_url = "https://geocoding-api.open-meteo.com/v1/search"
    forecast_url = "https://api.open-meteo.com/v1/forecast"

    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self._http_client = http_client
        self._retry_until = 0.0
        self._retry_reason = "rate_limited"

    async def get_current_weather(self, city: str) -> WeatherReport | None:
        query = normalize_text(city)
        if not query:
            raise WeatherLocationError("empty_query")
        parts = [part.strip() for part in query.split(",")]
        if len(query) > 200 or len(parts) > 3 or any(not part for part in parts) or len(parts[0]) < 2:
            raise WeatherLocationError("invalid_query")
        try:
            async with asyncio.timeout(_LOOKUP_TIMEOUT_SECONDS):
                matches = await self._find_city(parts)
                if not matches:
                    return None
                location, language = next(iter(matches.values()))
                payload = await self._get_json(self.forecast_url, {
                    "latitude": location["latitude"], "longitude": location["longitude"],
                    "current": "temperature_2m,weather_code,wind_speed_10m",
                    "temperature_unit": "celsius", "wind_speed_unit": "kmh",
                })
                current = payload["current"]
                code = current["weather_code"]
                if isinstance(code, bool) or not isinstance(code, int):
                    raise ValueError("Invalid weather code")
                return WeatherReport(
                    city=normalize_text(location["name"]),
                    temperature_celsius=_number(current["temperature_2m"]),
                    condition=WMO_CONDITIONS.get(code, "unknown conditions"),
                    wind_speed_kmh=_number(current["wind_speed_10m"], 0),
                    country=normalize_text(location.get("country") or location["country_code"]),
                    region=normalize_text(location.get("admin1", "")), language=language,
                )
        except WeatherLocationError:
            raise
        except (TimeoutError, httpx.TimeoutException) as error:
            raise WeatherServiceError("Weather request timed out.", reason="timeout") from error
        except httpx.HTTPStatusError as error:
            reason = "rate_limited" if error.response.status_code == 429 else "provider_failure"
            raise WeatherServiceError("Weather provider request failed.", reason=reason) from error
        except httpx.HTTPError as error:
            raise WeatherServiceError("Weather provider request failed.") from error
        except (KeyError, TypeError, ValueError, OverflowError) as error:
            raise WeatherServiceError("Invalid weather provider response.", reason="invalid_response") from error

    async def _get_json(self, url: str, params: dict) -> dict:
        if monotonic() < self._retry_until:
            raise WeatherServiceError("Weather provider asked clients to retry later.", reason=self._retry_reason)
        async with asyncio.timeout(_REQUEST_TIMEOUT_SECONDS):
            response = await self._http_client.get(
                url, params=params, timeout=_REQUEST_TIMEOUT_SECONDS, follow_redirects=False,
            )
        if response.status_code in {429, 503}:
            delay = _retry_after(response.headers.get("Retry-After", ""))
            if delay and (deadline := monotonic() + delay) > self._retry_until:
                self._retry_until = deadline
                self._retry_reason = "rate_limited" if response.status_code == 429 else "provider_failure"
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("error", False), bool):
            raise ValueError("Invalid provider object")
        if payload.get("error"):
            raise WeatherServiceError("Weather provider reported a failure.")
        return payload

    async def _matches(self, name: str, *, country: str | None = None,
                       region: str | None = None) -> dict[int, tuple[dict, WeatherLanguage]]:
        matches: dict[int, tuple[dict, WeatherLanguage]] = {}
        query = f"{name}, {region}" if region is not None else name
        name_key = _location_key(name)
        region_key = _location_key(region) if region is not None else None
        for language in _languages(name):
            params = {"name": query, "count": _RESULT_LIMIT, "language": language, "format": "json"}
            if country:
                params["countryCode"] = country
            payload = await self._get_json(self.geocoding_url, params)
            if "results" not in payload:
                # Open-Meteo omits results on an empty search, retaining generationtime_ms.
                _number(payload["generationtime_ms"], 0)
                results = []
            else:
                results = payload["results"]
            if not isinstance(results, list) or len(results) > _RESULT_LIMIT:
                raise ValueError("Invalid geocoding results")
            for location in results:
                if not isinstance(location, dict):
                    raise ValueError("Invalid geocoding candidate")
                feature = location["feature_code"]
                if not isinstance(feature, str) or not feature:
                    raise ValueError("Invalid geocoding feature code")
                if feature not in _SETTLEMENTS:
                    continue
                ident, label, code = (location[field] for field in ("id", "name", "country_code"))
                if (isinstance(ident, bool) or not isinstance(ident, int) or ident <= 0
                        or not isinstance(label, str) or not label.strip()
                        or not isinstance(code, str)
                        or not re.fullmatch(r"[A-Z]{2}", code)):
                    raise ValueError("Invalid geocoding candidate")
                _number(location["latitude"], -90, 90)
                _number(location["longitude"], -180, 180)
                for field in ("country", "admin1"):
                    if field in location and not isinstance(location[field], str):
                        raise ValueError("Invalid geocoding label")
                if (country is not None and code != country) or _location_key(label) != name_key:
                    continue
                if region_key is not None and _location_key(location.get("admin1", "")) != region_key:
                    continue
                if ident in matches and any(location[key] != matches[ident][0][key]
                                            for key in ("latitude", "longitude", "country_code")):
                    raise ValueError("Inconsistent geocoding identity")
                matches.setdefault(ident, (location, language))
        return matches

    async def _find_city(self, parts: list[str]) -> dict[int, tuple[dict, WeatherLanguage]]:
        city = parts[0]
        country = region = None
        if len(parts) == 3:
            region = parts[1]
            country = _country_code(parts[2])
            if country is None:
                raise WeatherLocationError("qualifier_mismatch")
        elif len(parts) == 2:
            country = _country_code(parts[1])
            region = parts[1] if country is None else None
        else:
            matches = await self._matches(city)
            if matches or (suffix := _country_suffix(city)) is None:
                return matches
            city, country = suffix
        # At most two city searches of three locales each, plus one forecast.
        matches = await self._matches(city, country=country, region=region)
        if not matches:
            raise WeatherLocationError("qualifier_mismatch")
        return matches
