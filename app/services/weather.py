"""Current weather lookup through Open-Meteo's public APIs."""

import asyncio
import math
import re
import unicodedata
from typing import Literal

import httpx

from app.services.contracts import WeatherReport
from app.utils.text import normalize_text


class WeatherServiceError(RuntimeError):
    """The weather provider could not complete a request."""

    def __init__(self, message: str, *, reason: str = "provider_failure") -> None:
        super().__init__(message)
        self.reason = reason


class WeatherLocationError(ValueError):
    """The location needs clarification, rather than another provider request."""

    def __init__(self, reason: Literal["invalid_query", "ambiguous"], *, options: tuple[str, ...] = ()) -> None:
        super().__init__(reason)
        self.reason = reason
        self.options = options


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


def _prominence(location: dict) -> int:
    feature = location["feature_code"]
    return {"PPLC": 4, "PPLA": 3, "PPLA2": 2, "PPLA3": 2, "PPLA4": 2,
            "PPLA5": 2, "PPL": 1, "PPLG": 1}.get(feature, 0)


def _dominates(city: dict, other: dict) -> bool:
    population, rival = city.get("population"), other.get("population")
    if population and rival is not None:
        # A modest size difference (e.g. the various Springfields) is not enough.
        return (population >= 50_000 and population >= 5 * max(rival, 1)
                and (_prominence(city) >= _prominence(other) or population >= 10 * max(rival, 1)))
    # Missing population is unknown, not zero. Only a national capital versus an
    # ordinary settlement/section has strong independent prominence evidence.
    return (city["feature_code"] == "PPLC" and _prominence(other) <= 1
            and (population is None or population >= 50_000)
            and (rival is None or rival <= 10_000))


def _short_label(value: str, limit: int = 64) -> str:
    value = normalize_text(value)
    if len(value.encode("utf-8")) <= limit:
        return value
    return value.encode("utf-8")[:limit - 3].decode("utf-8", errors="ignore") + "…"


def _clarification_options(matches: list[tuple[dict, "WeatherLanguage"]]) -> tuple[str, ...]:
    # Country codes and bounded labels keep three useful options within chat limits.
    locations = [item[0] for item in matches[:3]]
    labels = [f"{_short_label(p['name'], 36)}, {_short_label(p.get('admin1', ''), 36)}, {p['country_code']}"
              for p in locations]
    duplicates = {label for label in labels if labels.count(label) > 1}
    for index, place in enumerate(locations):
        if labels[index] in duplicates:
            # Same city/region labels still represent distinct GeoNames IDs.
            labels[index] = (f"{_short_label(place['name'], 18)}, {_short_label(place.get('admin1', ''), 18)}, "
                             f"{place['country_code']} (#{place['id']})")
    return tuple(labels)


def _select_city(matches: dict[int, tuple[dict, "WeatherLanguage"]]) -> tuple[dict, "WeatherLanguage"]:
    ranked = sorted(matches.values(), key=lambda item: (
        -(item[0].get("population") or 0), -_prominence(item[0]), item[0]["id"]))
    if len(ranked) == 1:
        return ranked[0]
    for candidate in ranked:
        if all(candidate is other or _dominates(candidate[0], other[0]) for other in ranked):
            return candidate
    raise WeatherLocationError("ambiguous", options=_clarification_options(ranked))


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
    location = report.city
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

    async def get_current_weather(self, city: str) -> WeatherReport | None:
        query = normalize_text(city)
        parts = [part.strip() for part in query.split(",")]
        if len(query) > 200 or len(parts) > 3 or any(not part for part in parts) or len(parts[0]) < 2:
            raise WeatherLocationError("invalid_query")
        try:
            async with asyncio.timeout(_LOOKUP_TIMEOUT_SECONDS):
                matches = await self._find_city(parts)
                if not matches:
                    return None
                location, language = _select_city(matches)
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
        async with asyncio.timeout(_REQUEST_TIMEOUT_SECONDS):
            response = await self._http_client.get(
                url, params=params, timeout=_REQUEST_TIMEOUT_SECONDS, follow_redirects=False,
            )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("error", False), bool):
            raise ValueError("Invalid provider object")
        if payload.get("error"):
            raise WeatherServiceError("Weather provider reported a failure.")
        return payload

    async def _matches(self, query: str, name: str, *, country: str | None = None,
                       countries: bool = False) -> dict[int, tuple[dict, WeatherLanguage]]:
        matches: dict[int, tuple[dict, WeatherLanguage]] = {}
        variants: dict[int, list[tuple[dict, WeatherLanguage]]] = {}
        # Public probes show locale-dependent search, not query translation. Always
        # inspect all three: e.g. Одеса/ru can return a different place from Одеса/uk.
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
                ident, label, feature, code = (location[field] for field in ("id", "name", "feature_code", "country_code"))
                if (isinstance(ident, bool) or not isinstance(ident, int) or ident <= 0
                        or not isinstance(label, str) or not label.strip()
                        or not isinstance(feature, str) or not feature or not isinstance(code, str)
                        or not re.fullmatch(r"[A-Z]{2}", code)):
                    raise ValueError("Invalid geocoding candidate")
                _number(location["latitude"], -90, 90)
                _number(location["longitude"], -180, 180)
                for field in ("country", "admin1"):
                    if field in location and not isinstance(location[field], str):
                        raise ValueError("Invalid geocoding label")
                if "population" in location:
                    _number(location["population"], 0)
                eligible = feature == "PCLI" if countries else feature.startswith("PPL")
                if eligible and (country is None or code == country):
                    if ident in variants and any(location[k] != variants[ident][0][0][k]
                                                 for k in ("latitude", "longitude", "country_code")):
                        raise ValueError("Inconsistent geocoding identity")
                    variants.setdefault(ident, []).append((location, language))
                    if _location_key(label) == _location_key(name):
                        matches.setdefault(ident, (location, language))
        # Exact matching in any locale establishes identity. Other translations
        # of that ID may supply omitted population; names alone never merge places.
        for ident, (location, language) in matches.items():
            populations = [p["population"] for p, _ in variants[ident] if "population" in p]
            if populations:
                matches[ident] = ({**location, "population": max(populations)}, language)
        return matches

    async def _country_code(self, name: str) -> str | None:
        if re.fullmatch(r"[a-zA-Z]{2}", name):
            return name.upper()
        matches = await self._matches(name, name, countries=True)
        if len(matches) > 1:
            raise WeatherLocationError("ambiguous", options=_clarification_options(list(matches.values())))
        return next(iter(matches.values()))[0]["country_code"] if matches else None

    async def _find_city(self, parts: list[str]) -> dict[int, tuple[dict, WeatherLanguage]]:
        city = parts[0]
        if len(parts) == 3:
            # The API ignores a third comma component. Resolve it separately and
            # constrain the city+region query, never silently discard a country.
            country = await self._country_code(parts[2])
            return await self._matches(", ".join(parts[:2]), city, country=country) if country else {}
        matches = await self._matches(", ".join(parts), city)
        if not matches and len(parts) == 2 and len(parts[1]) > 2:
            # Mixed-language country qualifiers can fail the provider's localized
            # qualifier index. Only rewrite after exact country-entity resolution;
            # otherwise retain the original region/country interpretation above.
            country = await self._country_code(parts[1])
            if country:
                matches = await self._matches(city, city, country=country)
        # At most 9 geocoding requests + 1 forecast; the outer deadline covers all.
        return matches
