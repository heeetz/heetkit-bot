"""Mocked regressions informed by real public Open-Meteo geocoding comparisons."""
import asyncio
import json

import httpx
import pytest

from app.services.contracts import WeatherReport
from app.services.weather import OpenMeteoWeatherService, WeatherLocationError, WeatherServiceError, format_weather_response


def place(name='Луцьк', *, ident=702569, country='UA', region='Волинська Область', feature='PPLA', **fields):
    return {'id': ident, 'name': name, 'latitude': 50.75784, 'longitude': 25.35024,
            'country_code': country, 'country': {'UA': 'Україна', 'US': 'United States', 'FR': 'France'}.get(country, country),
            'admin1': region, 'feature_code': feature, **fields}


CURRENT = {'temperature_2m': 17.2, 'weather_code': 3, 'wind_speed_10m': 14.0}


async def lookup(query, geocode, *, forecast=None):
    requests = []
    def handler(request):
        requests.append(request)
        if request.url.host == 'geocoding-api.open-meteo.com':
            result = geocode(request)
        else:
            assert request.url.host == 'api.open-meteo.com'
            result = {'current': CURRENT} if forecast is None else forecast
        return result if isinstance(result, httpx.Response) else httpx.Response(200, content=json.dumps(result).encode())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await OpenMeteoWeatherService(client).get_current_weather(query)
    return result, requests


@pytest.mark.asyncio
@pytest.mark.parametrize('query,spellings,language', [
    ('Луцьк', {'uk': 'Луцьк'}, 'uk'),
    ('Луцк', {'ru': 'Луцк'}, 'ru'),
    ('Lutsk', {'en': 'Lutsk', 'uk': 'Луцьк', 'ru': 'Луцк'}, 'en'),
    ('Львів', {'uk': 'Львів'}, 'uk'),
    ('Лондон', {'uk': 'Лондон', 'ru': 'Лондон', 'en': 'London'}, 'ru'),
])
async def test_all_locales_preserve_query_and_resolve_matching_unicode_name(query, spellings, language):
    def geocode(request):
        name = spellings.get(request.url.params['language'])
        return {'results': [place(name)] if name else []}
    report, requests = await lookup(query, geocode)
    assert report is not None and report.language == language
    assert report.city == spellings[language]
    assert report.temperature_celsius == 17.2 and report.condition == 'overcast'
    assert len(requests) == 4
    assert {r.url.params['language'] for r in requests[:3]} == {'en', 'ru', 'uk'}
    assert all(r.url.params['name'] == query and r.url.params['count'] == '10' for r in requests[:3])
    assert requests[-1].url.params['latitude'] == '50.75784'
    assert requests[-1].url.params['current'] == 'temperature_2m,weather_code,wind_speed_10m'
    assert all(set(r.extensions['timeout'].values()) == {2.0} for r in requests)


@pytest.mark.asyncio
@pytest.mark.parametrize('query,expected,name,country,region', [
    ('\tNew   York\u00a0', 'New York', 'New York', 'US', 'New York'),
    ('  Lutsk\u00a0,\tUkraine\n', 'Lutsk, Ukraine', 'Lutsk', 'UA', 'Volyn Oblast'),
    ("Кам'янець-Подільський", "Кам'янець-Подільський", 'Кам’янець-Подільський', 'UA', 'Хмельницька область'),
    ('Sao Paulo, Brazil', 'Sao Paulo, Brazil', 'São Paulo', 'BR', 'São Paulo'),
])
async def test_whitespace_apostrophes_accents_and_qualifiers(query, expected, name, country, region):
    report, requests = await lookup(query, lambda r: {'results': [place(name, country=country, region=region)]})
    assert report is not None and report.city == name
    assert all(r.url.params['name'] == expected for r in requests[:3])


@pytest.mark.asyncio
async def test_distinct_ukrainian_letters_are_not_removed_for_matching():
    report, requests = await lookup('Киів', lambda r: {'results': [place('Київ')]})
    assert report is None and len(requests) == 3


@pytest.mark.asyncio
async def test_lutsk_city_wins_over_exact_airport_and_fuzzy_prefix():
    report, _ = await lookup('Lutsk', lambda r: {'results': [
        place('Lutsk', ident=11269957, feature='AIRP'),
        place('Lutska', ident=702568, population=999999999), place('Lutsk'),
    ]})
    assert report is not None and report.city == 'Lutsk'


@pytest.mark.asyncio
async def test_unrelated_or_prefix_only_candidates_are_not_selected():
    report, requests = await lookup('Lutsk', lambda r: {'results': [place('Lutska'), place('Seattle', ident=2)]})
    assert report is None and len(requests) == 3


@pytest.mark.asyncio
async def test_odessa_other_locale_is_checked_even_after_an_exact_russian_match():
    requests = []
    def geocode(r):
        requests.append(r)
        if r.url.params['language'] == 'ru':
            return {'results': [place('Одеса', ident=11300817, country='LT', region='Vilnius')]}
        return {'results': [place('Одеса', ident=698740)] if r.url.params['language'] == 'uk' else []}
    with pytest.raises(WeatherLocationError, match='ambiguous'):
        await lookup('Одеса', geocode)
    assert len(requests) == 3


@pytest.mark.asyncio
async def test_ambiguous_same_name_cities_are_not_resolved_by_population():
    with pytest.raises(WeatherLocationError, match='ambiguous'):
        await lookup('Springfield', lambda r: {'results': [
            place('Springfield', ident=1, country='US', region='Missouri', population=200000),
            place('Springfield', ident=2, country='US', region='Illinois', population=100000),
        ]})


@pytest.mark.asyncio
async def test_region_and_explicit_country_are_both_sent_to_provider():
    def geocode(r):
        assert r.url.params['name'] == 'Springfield, Illinois'
        assert r.url.params['countryCode'] == 'US'
        return {'results': [place('Springfield', country='US', region='Illinois')]}
    report, requests = await lookup('Springfield, Illinois, US', geocode)
    assert report and report.region == 'Illinois' and report.country == 'United States'
    assert len(requests) == 4


@pytest.mark.asyncio
async def test_third_qualifier_is_not_ignored_or_relaxed_on_empty_results():
    def geocode(r):
        assert r.url.params['name'] == 'Paris, Texas' and r.url.params['countryCode'] == 'FR'
        return {'results': [place('Paris', country='US', region='Texas')]}
    report, requests = await lookup('Paris, Texas, FR', geocode)
    assert report is None and len(requests) == 3


@pytest.mark.asyncio
async def test_full_country_name_is_resolved_for_city_region_country():
    def geocode(r):
        p = r.url.params
        if p['name'] == 'United States':
            return {'results': [place('United States', ident=6252001, country='US', feature='PCLI')]}
        assert p['name'] == 'Springfield, Illinois' and p['countryCode'] == 'US'
        return {'results': [place('Springfield', country='US', region='Illinois')]}
    report, requests = await lookup('Springfield, Illinois, United States', geocode)
    assert report is not None and len(requests) == 7


@pytest.mark.asyncio
async def test_mixed_language_country_fallback_preserves_country_and_request_budget():
    def geocode(r):
        p = r.url.params
        if p['name'] == 'Луцьк, Украина':
            return {'results': []}
        if p['name'] == 'Украина':
            return {'results': [place('Украина', ident=690791, feature='PCLI')] if p['language'] == 'ru' else []}
        assert p['name'] == 'Луцьк' and p['countryCode'] == 'UA'
        return {'results': [place()] if p['language'] == 'uk' else []}
    report, requests = await lookup('Луцьк, Украина', geocode)
    assert report is not None and report.language == 'uk' and len(requests) == 10
    assert {r.url.params['countryCode'] for r in requests[6:9]} == {'UA'}


@pytest.mark.asyncio
async def test_admin_country_name_collision_keeps_original_region_interpretation():
    report, requests = await lookup('Atlanta, Georgia', lambda r: {'results': [place('Atlanta', country='US', region='Georgia')]})
    assert report is not None and len(requests) == 4
    assert all(r.url.params['name'] == 'Atlanta, Georgia' and 'countryCode' not in r.url.params for r in requests[:3])


@pytest.mark.asyncio
@pytest.mark.parametrize('empty', [{'results': []}, {'generationtime_ms': 0.2}])
async def test_clean_empty_search_is_not_found(empty):
    report, requests = await lookup('Unknown City', lambda r: empty)
    assert report is None and len(requests) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize('query', ['', '  ', 'Lutsk,', 'Lutsk,,UA', 'Lutsk, Volyn, UA, Europe', 'A', 'x' * 201])
async def test_invalid_query_does_not_call_provider(query):
    def forbidden(r):
        raise AssertionError('Invalid input must not issue requests')
    with pytest.raises(WeatherLocationError, match='invalid_query'):
        await lookup(query, forbidden)


@pytest.mark.asyncio
@pytest.mark.parametrize('payload', [
    {}, [], {'results': None}, {'results': {}}, {'results': [None]}, {'error': 'invalid'},
    {'results': [place(latitude=float('nan'))]}, {'results': [place(longitude=181)]},
    {'results': [place(id=True)]}, {'results': [place(name=42)]}, {'results': [place(country_code=None)]},
    {'results': [place(admin1=None)]}, {'generationtime_ms': 'invalid'},
])
async def test_malformed_geocoding_is_not_not_found(payload):
    with pytest.raises(WeatherServiceError) as caught:
        await lookup('Луцьк', lambda r: payload)
    assert caught.value.reason == 'invalid_response'
    assert 'private provider body' not in str(caught.value)


@pytest.mark.asyncio
async def test_provider_declared_failure_is_not_an_empty_search():
    with pytest.raises(WeatherServiceError) as caught:
        await lookup('Луцьк', lambda r: {'error': True, 'reason': 'private provider body'})
    assert caught.value.reason == 'provider_failure'
    assert 'private provider body' not in str(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize('status,reason', [(429, 'rate_limited'), (503, 'provider_failure'), (400, 'provider_failure'), (302, 'provider_failure')])
async def test_http_failures_are_not_not_found_or_followed(status, reason):
    with pytest.raises(WeatherServiceError) as caught:
        await lookup('Луцьк', lambda r: httpx.Response(status, headers={'Location': 'https://unrelated.invalid'}))
    assert caught.value.reason == reason


@pytest.mark.asyncio
async def test_failure_after_empty_or_matching_locale_is_not_hidden():
    for initial in ([], [place('Lutsk')]):
        def geocode(r):
            return {'results': initial} if r.url.params['language'] == 'en' else httpx.Response(503)
        with pytest.raises(WeatherServiceError) as caught:
            await lookup('Lutsk', geocode)
        assert caught.value.reason == 'provider_failure'


@pytest.mark.asyncio
@pytest.mark.parametrize('error,reason', [(httpx.ReadTimeout('private'), 'timeout'), (httpx.ConnectError('private'), 'provider_failure')])
async def test_transport_failures_keep_safe_categories(error, reason):
    def geocode(r):
        raise error
    with pytest.raises(WeatherServiceError) as caught:
        await lookup('Луцьк', geocode)
    assert caught.value.reason == reason and 'private' not in str(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize('payload', [
    {'current': None}, {'current': {}}, {'current': {**CURRENT, 'temperature_2m': None}},
    {'current': {**CURRENT, 'temperature_2m': float('inf')}},
    {'current': {**CURRENT, 'weather_code': True}}, {'current': {**CURRENT, 'wind_speed_10m': -1}},
    httpx.Response(200, content=b'not json'),
])
async def test_malformed_forecast_is_not_not_found(payload):
    with pytest.raises(WeatherServiceError) as caught:
        await lookup('Луцьк', lambda r: {'results': [place()]}, forecast=payload)
    assert caught.value.reason == 'invalid_response'


@pytest.mark.asyncio
async def test_forecast_rate_limit_is_not_city_not_found():
    with pytest.raises(WeatherServiceError) as caught:
        await lookup('Луцьк', lambda r: {'results': [place()]}, forecast=httpx.Response(429))
    assert caught.value.reason == 'rate_limited'


@pytest.mark.asyncio
@pytest.mark.parametrize('deadline', ['_LOOKUP_TIMEOUT_SECONDS', '_REQUEST_TIMEOUT_SECONDS'])
async def test_whole_operation_deadline_and_external_cancellation(monkeypatch, deadline):
    monkeypatch.setattr('app.services.weather.' + deadline, 0.01)
    async def slow(r):
        await asyncio.sleep(1)
        return httpx.Response(200, json={'results': []})
    async with httpx.AsyncClient(transport=httpx.MockTransport(slow)) as client:
        with pytest.raises(WeatherServiceError) as caught:
            await OpenMeteoWeatherService(client).get_current_weather('Луцьк')
        assert caught.value.reason == 'timeout'
    async def cancelled(r):
        raise asyncio.CancelledError
    async with httpx.AsyncClient(transport=httpx.MockTransport(cancelled)) as client:
        with pytest.raises(asyncio.CancelledError):
            await OpenMeteoWeatherService(client).get_current_weather('Луцьк')


def test_success_labels_city_region_country_and_resolved_language():
    report = WeatherReport('Луцьк', 17.2, 'overcast', 14, country='Україна', region='Волинська область', language='uk')
    assert format_weather_response(report, 'Луцьк') == 'Луцьк, Волинська область, Україна: +17.2°C, хмарно, вітер 14 км/год.'
