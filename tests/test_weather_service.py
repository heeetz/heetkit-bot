"""Tests for the Open-Meteo weather adapter."""

import httpx
import pytest

from app.services.weather import OpenMeteoWeatherService, WeatherServiceError


@pytest.mark.asyncio
async def test_weather_service_geocodes_and_fetches_current_conditions() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "geocoding-api.open-meteo.com":
            return httpx.Response(200, json={"results": [{"name": "New York", "latitude": 40.7, "longitude": -74.0}]})
        return httpx.Response(200, json={"current": {"temperature_2m": 17.2, "weather_code": 3, "wind_speed_10m": 14.0}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        report = await OpenMeteoWeatherService(client).get_current_weather("New   York")

    assert report is not None
    assert report.city == "New York"
    assert report.temperature_celsius == 17.2
    assert report.condition == "overcast"
    assert report.wind_speed_kmh == 14.0
    assert requests[0].url.params["name"] == "New York"
    assert requests[0].url.params["language"] == "en"
    assert requests[1].url.params["current"] == "temperature_2m,weather_code,wind_speed_10m"


@pytest.mark.asyncio
async def test_weather_service_returns_none_when_city_is_not_found() -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"results": []}))) as client:
        report = await OpenMeteoWeatherService(client).get_current_weather("Unknown City")

    assert report is None


@pytest.mark.asyncio
async def test_weather_service_geocodes_cyrillic_city_names_in_russian() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "geocoding-api.open-meteo.com":
            return httpx.Response(
                200,
                json={"results": [{"name": "Киев", "latitude": 50.45, "longitude": 30.52}]},
            )
        return httpx.Response(
            200,
            json={"current": {"temperature_2m": 12.0, "weather_code": 0, "wind_speed_10m": 8.0}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        report = await OpenMeteoWeatherService(client).get_current_weather("Киев")

    assert report is not None
    assert report.city == "Киев"
    assert requests[0].url.params["name"] == "Киев"
    assert requests[0].url.params["language"] == "ru"
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_weather_service_retries_geocoding_in_the_other_language() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "geocoding-api.open-meteo.com":
            if request.url.params["language"] == "ru":
                return httpx.Response(200, json={"results": []})
            return httpx.Response(
                200,
                json={"results": [{"name": "Lisbon", "latitude": 38.72, "longitude": -9.14}]},
            )
        return httpx.Response(
            200,
            json={"current": {"temperature_2m": 19.0, "weather_code": 1, "wind_speed_10m": 11.0}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        report = await OpenMeteoWeatherService(client).get_current_weather("лиссабон")

    assert report is not None
    assert report.city == "Lisbon"
    assert [request.url.params["language"] for request in requests[:2]] == ["ru", "en"]
    assert [request.url.params["name"] for request in requests[:2]] == ["лиссабон", "лиссабон"]


@pytest.mark.asyncio
async def test_weather_service_wraps_provider_failures() -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(503))) as client:
        with pytest.raises(WeatherServiceError):
            await OpenMeteoWeatherService(client).get_current_weather("London")