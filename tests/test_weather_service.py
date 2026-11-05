"""Mocked regressions informed by real public Open-Meteo geocoding comparisons."""
import asyncio
import json
from pathlib import Path

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
    ('  Lutsk\u00a0,\tuKRAINE\n', 'Lutsk', 'Lutsk', 'UA', 'Volyn Oblast'),
    ("Кам'янець-Подільський", "Кам'янець-Подільський", 'Кам’янець-Подільський', 'UA', 'Хмельницька область'),
    ('Sao Paulo, Brazil', 'Sao Paulo', 'São Paulo', 'BR', 'São Paulo'),
    ('Ростов-на-Дону', 'Ростов-на-Дону', 'Ростов-на-Дону', 'RU', 'Ростовская область'),
])
async def test_whitespace_apostrophes_accents_and_qualifiers(query, expected, name, country, region):
    report, requests = await lookup(query, lambda r: {'results': [place(name, country=country, region=region)]})
    assert report is not None and report.city == name
    assert all(r.url.params['name'] == expected for r in requests[:3])
    if ',' in query:
        assert all(r.url.params['countryCode'] == country for r in requests[:3])


@pytest.mark.asyncio
async def test_distinct_ukrainian_letters_are_not_removed_for_matching():
    report, requests = await lookup('Киів', lambda r: {'results': [place('Київ')]})
    assert report is None and len(requests) == 3


@pytest.mark.asyncio
async def test_lutsk_city_wins_over_exact_airport_district_and_fuzzy_prefix():
    report, requests = await lookup('Lutsk', lambda r: {'results': [
        place('Lutsk', ident=11269957, feature='AIRP'),
        place('Lutsk', ident=3, feature='PPLX', latitude=55),
        place('Lutska', ident=702568, population=999999999), place('Lutsk'),
    ]})
    assert report is not None and report.city == 'Lutsk'
    assert requests[-1].url.params['latitude'] == '50.75784'


@pytest.mark.asyncio
async def test_unrelated_or_prefix_only_candidates_are_not_selected():
    report, requests = await lookup('Lutsk', lambda r: {'results': [place('Lutska'), place('Seattle', ident=2)]})
    assert report is None and len(requests) == 3


@pytest.mark.asyncio
async def test_preferred_locale_wins_even_if_a_later_locale_has_a_larger_city():
    requests = []
    def geocode(r):
        requests.append(r)
        if r.url.params['language'] == 'ru':
            return {'results': [place('Одеса', ident=11300817, country='LT', region='Vilnius')]}
        return {'results': [place('Одеса', ident=698740)] if r.url.params['language'] == 'uk' else []}
    report, _ = await lookup('Одеса', geocode)
    assert report and report.region == 'Vilnius' and report.language == 'ru'
    assert len(requests) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize('query,ident,language', [
    ('Київ', 703448, 'uk'), ('Киев', 703448, 'ru'), ('Kyiv', 703448, 'en'),
    # The public index does not return Ukraine's capital for this alias.
    ('Kiev', 827619, 'en'),
    ('Луцьк', 702569, 'uk'), ('Луцк', 702569, 'ru'), ('Lutsk', 702569, 'en'),
    ('Paris', 2988507, 'en'),
])
async def test_verified_public_multilingual_candidates(query, ident, language):
    evidence = json.loads((Path(__file__).parent / 'fixtures/weather_geocoding.json').read_text(encoding='utf-8'))
    def geocode(request):
        return {'results': evidence[query][request.url.params['language']]}
    report, requests = await lookup(query, geocode)
    expected = next(p for p in evidence[query][language] if p['id'] == ident)
    assert report and report.city == expected['name'] and report.language == language
    assert requests[-1].url.params['latitude'] == str(expected['latitude'])
    assert requests[-1].url.params['longitude'] == str(expected['longitude'])
    assert len(requests) == 4


@pytest.mark.asyncio
@pytest.mark.parametrize('reverse', [False, True])
async def test_real_springfields_follow_provider_order(reverse):
    evidence = json.loads((Path(__file__).parent / 'fixtures/weather_geocoding.json').read_text(encoding='utf-8'))
    def geocode(request):
        candidates = evidence['Springfield'][request.url.params['language']]
        return {'results': list(reversed(candidates)) if reverse else candidates}
    report, requests = await lookup('Springfield', geocode)
    expected = evidence['Springfield']['en'][-1 if reverse else 0]
    assert report and report.region == expected['admin1']
    assert requests[-1].url.params['latitude'] == str(expected['latitude'])


@pytest.mark.asyncio
async def test_repeated_localized_matches_keep_first_locale_and_one_forecast():
    def geocode(r):
        if r.url.params['language'] == 'en':
            return {'results': [place('Capital', ident=1, feature='PPLA'), place('Capital', ident=2, population=100)]}
        return {'results': [place('Capital', ident=1, feature='PPLA', country='UA', population=None)]}
    report, requests = await lookup('Capital', geocode)
    assert report and report.city == 'Capital' and report.language == 'en'
    assert len(requests) == 4


@pytest.mark.asyncio
async def test_same_id_with_conflicting_coordinates_is_provider_failure():
    def geocode(r):
        return {'results': [place('Capital',
                                  latitude=50 if r.url.params['language'] == 'en' else 51)]}
    with pytest.raises(WeatherServiceError) as caught:
        await lookup('Capital', geocode)
    assert caught.value.reason == 'invalid_response'


@pytest.mark.asyncio
async def test_country_filter_excludes_dominant_capital_elsewhere():
    report, requests = await lookup('Paris, Texas, US', lambda r: {'results': [
        place('Paris', ident=2988507, country='FR', feature='PPLC', population=2_138_551),
        place('Paris', ident=4717560, country='US', region='Texas', population=24_782)]})
    assert report and report.region == 'Texas' and report.country == 'United States'
    assert all(r.url.params['countryCode'] == 'US' for r in requests[:3])


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
    with pytest.raises(WeatherLocationError, match='qualifier_mismatch'):
        await lookup('Paris, Texas, FR', geocode)


@pytest.mark.asyncio
async def test_full_country_name_is_resolved_for_city_region_country():
    def geocode(r):
        p = r.url.params
        assert p['name'] == 'Springfield, Illinois' and p['countryCode'] == 'US'
        return {'results': [place('Springfield', country='US', region='Illinois')]}
    report, requests = await lookup('Springfield, Illinois, United States', geocode)
    assert report is not None and len(requests) == 4


@pytest.mark.asyncio
async def test_mixed_language_country_uses_country_code_from_first_request():
    def geocode(r):
        p = r.url.params
        assert p['name'] == 'Луцьк' and p['countryCode'] == 'UA'
        return {'results': [place()] if p['language'] == 'uk' else []}
    report, requests = await lookup('Луцьк, Украина', geocode)
    assert report is not None and report.language == 'uk' and len(requests) == 4


@pytest.mark.asyncio
async def test_region_only_qualifier_filters_wrong_region_even_if_provider_returns_it():
    report, requests = await lookup('Springfield, Illinois', lambda r: {'results': [
        place('Springfield', ident=1, country='US', region='Missouri'),
        place('Springfield', ident=2, country='US', region='Illinois'),
    ]})
    assert report is not None and len(requests) == 4
    assert report.region == 'Illinois'
    assert all(r.url.params['name'] == 'Springfield, Illinois' and 'countryCode' not in r.url.params for r in requests[:3])


@pytest.mark.asyncio
@pytest.mark.parametrize('query,city,country,whole', [
    ('Київ, Україна', 'Київ', 'UA', False), ('Київ, ua', 'Київ', 'UA', False),
    ('London, CA', 'London', 'CA', False), ('Лондон, Канада', 'Лондон', 'CA', False),
    ('Лондон Канада', 'Лондон', 'CA', True), ('Київ UA', 'Київ', 'UA', True),
    ('London United Kingdom', 'London', 'GB', True),
    ('New York United States', 'New York', 'US', True),
])
async def test_explicit_countries_and_country_suffixes_are_strict(query, city, country, whole):
    def geocode(r):
        p = r.url.params
        if p['name'] == query and whole:
            assert 'countryCode' not in p
            return {'results': [place(city, country='FR')]}
        assert p['name'] == city and p['countryCode'] == country
        return {'results': [place(city, country='FR', ident=1), place(city, country=country)]}
    report, requests = await lookup(query, geocode)
    assert report and report.country != 'France'
    assert len(requests) == (7 if whole else 4)


@pytest.mark.asyncio
async def test_country_like_suffix_is_ignored_when_whole_city_is_exact():
    report, requests = await lookup('Example Canada', lambda r: {'results': [place('Example Canada', country='US')]})
    assert report and report.city == 'Example Canada' and report.country == 'United States'
    assert len(requests) == 4 and all('countryCode' not in r.url.params for r in requests)


@pytest.mark.asyncio
@pytest.mark.parametrize('query', ['Лондон, Канада', 'Лондон Канада', 'Лондон, Ontario, CA'])
async def test_qualifier_mismatch_never_forecasts_for_a_city_outside_country(query):
    def geocode(r):
        if r.url.params['name'] == query and ',' not in query:
            assert 'countryCode' not in r.url.params
        else:
            assert r.url.params['countryCode'] == 'CA'
        return {'results': [place('Лондон', country='GB', region='England')]}
    with pytest.raises(WeatherLocationError, match='qualifier_mismatch'):
        await lookup(query, geocode)


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
    with pytest.raises(WeatherLocationError, match='invalid_query' if query.strip() else 'empty_query'):
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
@pytest.mark.parametrize('status,header,reason', [
    (429, '15', 'rate_limited'),
    (503, 'Thu, 01 Jan 1970 00:01:55 GMT', 'provider_failure'),
])
async def test_provider_retry_after_blocks_network_without_waiting_or_extending(status, header, reason, monkeypatch):
    now = 100.0
    monkeypatch.setattr('app.services.weather.monotonic', lambda: now)
    monkeypatch.setattr('app.services.weather.time', lambda: 100.0)
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(status, headers={'Retry-After': header}, json={'reason': 'private provider body'})
        if request.url.host == 'geocoding-api.open-meteo.com':
            return httpx.Response(200, json={'results': [place('Lutsk')]})
        return httpx.Response(200, json={'current': CURRENT})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = OpenMeteoWeatherService(client)
        for now in (100.0, 114.0):
            with pytest.raises(WeatherServiceError) as caught:
                await service.get_current_weather('Lutsk')
            assert caught.value.reason == reason
            assert 'private provider body' not in str(caught.value)
            assert len(requests) == 1
        now = 115.0
        assert await service.get_current_weather('Lutsk') is not None
    assert len(requests) == 5


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


def test_success_labels_city_country_and_resolved_language():
    report = WeatherReport('Луцьк', 17.2, 'overcast', 14, country='Україна', region='Волинська область', language='uk')
    assert format_weather_response(report, 'Луцьк') == 'Луцьк, Україна: +17.2°C, хмарно, вітер 14 км/год.'
