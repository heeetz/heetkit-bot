import asyncio
import json

import pytest
from pydantic import SecretStr

from app.services import ai_balance
from app.services.ai_balance import AIBalance


BALANCES = [{
    "currency": "USD",
    "total_balance": "10.00",
    "granted_balance": "2.00",
    "topped_up_balance": "8.00",
}]


@pytest.mark.asyncio
async def test_deepseek_transport_and_balance_fields_are_bounded_and_sanitized(monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def aiter_bytes(self):
            yield json.dumps({
                "is_available": True,
                "balance_infos": BALANCES + [{
                    "currency": "EUR", "total_balance": "1", "granted_balance": "1",
                    "topped_up_balance": "0",
                }],
            }).encode()

    class FakeClient:
        def __init__(self, **kwargs):
            captured["client_options"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def stream(self, method, url, **kwargs):
            captured.update(method=method, url=url, request=kwargs)
            return FakeResponse()

    monkeypatch.setattr(ai_balance.httpx, "AsyncClient", FakeClient)
    service = AIBalance()
    result = await asyncio.wait_for(service.get("DeepSeek", SecretStr("synthetic-secret")), 2)

    assert result["ok"] is True
    assert result["provider"] == "deepseek"
    assert result["state"] == "available"
    assert result["balances"] == BALANCES
    assert result["updated_at"].endswith("Z")
    assert captured["method"] == "GET"
    assert captured["url"] == "https://api.deepseek.com/user/balance"
    assert captured["request"]["headers"]["Authorization"] == "Bearer synthetic-secret"
    assert captured["client_options"]["follow_redirects"] is False
    assert captured["client_options"]["trust_env"] is False
    assert captured["client_options"]["timeout"].read == ai_balance.BALANCE_TRANSPORT_TIMEOUT_SECONDS
    assert "synthetic-secret" not in repr(service._cache)


@pytest.mark.asyncio
async def test_cache_is_reused_for_sixty_seconds_and_refresh_forces_lookup(monkeypatch):
    now = [100.0]
    calls = 0

    async def request(_key):
        nonlocal calls
        calls += 1
        return BALANCES

    monkeypatch.setattr(ai_balance.time, "monotonic", lambda: now[0])
    service = AIBalance()
    monkeypatch.setattr(service, "_request_balance", request)

    first = await service.get("deepseek", "synthetic-secret")
    second = await service.get("deepseek", "synthetic-secret")
    forced = await service.get("deepseek", "synthetic-secret", refresh=True)
    now[0] += 60
    expired = await service.get("deepseek", "synthetic-secret")

    assert calls == 2
    assert first["updated_at"] == second["updated_at"]
    assert forced["updated_at"] == first["updated_at"]
    assert expired["updated_at"] != first["updated_at"]


@pytest.mark.asyncio
async def test_failed_refresh_returns_last_success_as_stale(monkeypatch):
    now = [0.0]
    calls = 0

    async def request(_key):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise RuntimeError("synthetic-secret must never escape")
        return BALANCES

    monkeypatch.setattr(ai_balance.time, "monotonic", lambda: now[0])
    service = AIBalance()
    monkeypatch.setattr(service, "_request_balance", request)
    original = await service.get("deepseek", "synthetic-secret")
    now[0] += 61
    stale = await service.get("deepseek", "synthetic-secret", refresh=True)
    still_stale = await service.get("deepseek", "synthetic-secret", refresh=True)

    assert calls == 2
    assert stale["state"] == "stale"
    assert stale["balances"] == BALANCES
    assert stale["updated_at"] == original["updated_at"]
    assert "temporarily unavailable" in stale["error"]
    assert still_stale == stale
    assert "synthetic-secret" not in repr(stale)


@pytest.mark.asyncio
async def test_concurrent_refreshes_share_one_request(monkeypatch):
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def request(_key):
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return BALANCES

    service = AIBalance()
    monkeypatch.setattr(service, "_request_balance", request)
    one = asyncio.create_task(service.get("deepseek", "same-key"))
    two = asyncio.create_task(service.get("deepseek", "same-key", refresh=True))
    await started.wait()
    release.set()
    results = await asyncio.gather(one, two)

    assert calls == 1
    assert results[0] == results[1]


@pytest.mark.asyncio
async def test_unsupported_or_unconfigured_provider_is_unavailable_without_request(monkeypatch):
    service = AIBalance()

    async def fail_if_called(_key):
        raise AssertionError("unexpected network request")

    monkeypatch.setattr(service, "_request_balance", fail_if_called)
    unsupported = await service.get("openai", "synthetic-secret")
    missing = await service.get("deepseek", None)

    assert unsupported["state"] == "unavailable"
    assert unsupported["balances"] == [] and unsupported["updated_at"] is None
    assert missing["state"] == "unavailable"


@pytest.mark.asyncio
async def test_http_and_malformed_response_failures_are_generic(monkeypatch):
    class FakeResponse:
        status_code = 401

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def aiter_bytes(self):
            yield b'{"error":"synthetic-secret provider detail"}'

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def stream(self, *_args, **_kwargs):
            return FakeResponse()

    monkeypatch.setattr(ai_balance.httpx, "AsyncClient", FakeClient)
    result = await AIBalance().get("deepseek", "synthetic-secret")

    assert result["state"] == "unavailable"
    assert result["error"] == ai_balance._BALANCE_ERROR
    assert "synthetic-secret" not in repr(result)
    assert "provider detail" not in repr(result)


@pytest.mark.asyncio
async def test_empty_balance_payload_is_unavailable(monkeypatch):
    class FakeResponse:
        status_code = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def aiter_bytes(self):
            yield b'{"is_available":false,"balance_infos":[]}'

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def stream(self, *_args, **_kwargs):
            return FakeResponse()

    monkeypatch.setattr(ai_balance.httpx, "AsyncClient", FakeClient)
    result = await AIBalance().get("deepseek", "synthetic-secret")

    assert result["state"] == "unavailable"
    assert result["balances"] == [] and result["updated_at"] is None
    assert "synthetic-secret" not in repr(result)
