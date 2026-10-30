"""On-demand, bounded balance lookup for supported AI providers."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from pydantic import SecretStr

DEEPSEEK_BALANCE_URL = "https://api.deepseek.com/user/balance"
BALANCE_CACHE_TTL_SECONDS = 60.0
BALANCE_REQUEST_TIMEOUT_SECONDS = 8.0
BALANCE_TRANSPORT_TIMEOUT_SECONDS = 6.0
BALANCE_MAX_RESPONSE_BYTES = 64 * 1024
BALANCE_MAX_CACHE_ENTRIES = 16
_BALANCE_ERROR = "Balance is temporarily unavailable. Try again later."
_BALANCE_VALUE = re.compile(r"^[0-9]{1,18}(?:\.[0-9]{1,12})?$")


@dataclass(frozen=True)
class _CachedBalance:
    balances: tuple[dict[str, str], ...]
    updated_at: str
    cached_at: float


class AIBalance:
    """Fetch and cache provider balance data without retaining API credentials."""

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], _CachedBalance] = {}
        self._inflight: dict[tuple[str, str], asyncio.Task[_CachedBalance]] = {}
        self._last_attempt: dict[tuple[str, str], float] = {}
        self._failed: set[tuple[str, str]] = set()
        self._lock = asyncio.Lock()
        self._closed = False

    async def get(
        self, provider: str, key: str | SecretStr | None, *, refresh: bool = False,
    ) -> dict[str, Any]:
        provider_id = provider.strip().lower() if isinstance(provider, str) else ""
        if provider_id != "deepseek":
            return self._unavailable(provider_id or "unknown", "Balance lookup is not supported for this provider.")

        secret = self._read_key(key)
        if not secret:
            return self._unavailable(provider_id, "A provider connection is not configured.")

        cache_key = (provider_id, hashlib.sha256(secret.encode("utf-8")).hexdigest())
        async with self._lock:
            if self._closed:
                return self._unavailable(provider_id, _BALANCE_ERROR)

            cached = self._cache.get(cache_key)
            task = self._inflight.get(cache_key)
            if task is None:
                now = time.monotonic()
                attempted_at = self._last_attempt.get(cache_key)
                if (attempted_at is not None
                        and now - attempted_at < BALANCE_CACHE_TTL_SECONDS):
                    if cached is not None:
                        state = "stale" if cache_key in self._failed else "available"
                        error = _BALANCE_ERROR if cache_key in self._failed else None
                        return self._result(provider_id, cached, state, error)
                    return self._unavailable(provider_id, _BALANCE_ERROR)
                if (cached is not None
                        and now - cached.cached_at < BALANCE_CACHE_TTL_SECONDS):
                    return self._result(provider_id, cached, "available")

                self._remember_attempt(cache_key, now)
                task = asyncio.create_task(self._fetch_and_cache(cache_key, secret))
                self._inflight[cache_key] = task
                task.add_done_callback(self._observe_task)

        try:
            current = await asyncio.shield(task)
        except asyncio.CancelledError:
            raise
        except Exception:
            async with self._lock:
                self._failed.add(cache_key)
                previous = self._cache.get(cache_key)
            if previous is not None:
                return self._result(provider_id, previous, "stale", _BALANCE_ERROR)
            return self._unavailable(provider_id, _BALANCE_ERROR)
        return self._result(provider_id, current, "available")

    def _remember_attempt(self, cache_key: tuple[str, str], at: float) -> None:
        if cache_key not in self._last_attempt and len(self._last_attempt) >= BALANCE_MAX_CACHE_ENTRIES:
            oldest = min(self._last_attempt, key=self._last_attempt.get)
            self._last_attempt.pop(oldest, None)
            self._cache.pop(oldest, None)
            self._failed.discard(oldest)
        self._last_attempt[cache_key] = at

    @staticmethod
    def _observe_task(task: asyncio.Task[_CachedBalance]) -> None:
        if not task.cancelled():
            task.exception()

    async def aclose(self) -> None:
        """Cancel outstanding lookups and return within a short bounded interval."""
        async with self._lock:
            self._closed = True
            tasks = list(self._inflight.values())
            for task in tasks:
                task.cancel()
        if tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True), timeout=1.0,
                )
            except TimeoutError:
                pass

    @staticmethod
    def _read_key(key: str | SecretStr | None) -> str | None:
        if isinstance(key, SecretStr):
            value = key.get_secret_value()
        elif isinstance(key, str):
            value = key
        else:
            return None
        value = value.strip()
        return value or None

    async def _fetch_and_cache(self, cache_key: tuple[str, str], key: str) -> _CachedBalance:
        try:
            async with asyncio.timeout(BALANCE_REQUEST_TIMEOUT_SECONDS):
                balances = await self._request_balance(key)
            now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            entry = _CachedBalance(tuple(balances), now, time.monotonic())
            async with self._lock:
                if cache_key not in self._cache and len(self._cache) >= BALANCE_MAX_CACHE_ENTRIES:
                    oldest = min(self._cache, key=lambda item: self._last_attempt.get(item, 0.0))
                    if oldest != cache_key:
                        self._cache.pop(oldest, None)
                        self._last_attempt.pop(oldest, None)
                        self._failed.discard(oldest)
                self._cache[cache_key] = entry
                self._failed.discard(cache_key)
            return entry
        except asyncio.CancelledError:
            raise
        except Exception:
            async with self._lock:
                self._failed.add(cache_key)
            raise
        finally:
            async with self._lock:
                self._inflight.pop(cache_key, None)

    async def _request_balance(self, key: str) -> list[dict[str, str]]:
        timeout = httpx.Timeout(BALANCE_TRANSPORT_TIMEOUT_SECONDS)
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=False, trust_env=False,
        ) as client:
            async with client.stream(
                "GET",
                DEEPSEEK_BALANCE_URL,
                headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
            ) as response:
                if response.status_code != 200:
                    raise ValueError("Balance request failed.")
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > BALANCE_MAX_RESPONSE_BYTES:
                        raise ValueError("Balance response exceeded its size limit.")
                    chunks.append(chunk)

        payload = json.loads(b"".join(chunks))
        if (not isinstance(payload, dict) or not isinstance(payload.get("balance_infos"), list)
                or not isinstance(payload.get("is_available"), bool)):
            raise ValueError("Balance response was invalid.")
        result: list[dict[str, str]] = []
        for item in payload["balance_infos"][:4]:
            if not isinstance(item, dict):
                continue
            currency = item.get("currency")
            if currency not in {"CNY", "USD"}:
                continue
            values = {
                name: self._valid_amount(item.get(name))
                for name in ("total_balance", "granted_balance", "topped_up_balance")
            }
            if any(value is None for value in values.values()):
                continue
            result.append({"currency": currency, **values})  # type: ignore[dict-item]
        if not result:
            raise ValueError("Balance response contained no supported balances.")
        return result

    @staticmethod
    def _valid_amount(value: object) -> str | None:
        if not isinstance(value, str) or not _BALANCE_VALUE.fullmatch(value):
            return None
        try:
            amount = Decimal(value)
        except InvalidOperation:
            return None
        return value if amount.is_finite() and amount >= 0 else None

    @staticmethod
    def _result(
        provider: str, entry: _CachedBalance, state: str, error: str | None = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "ok": True,
            "provider": provider,
            "state": state,
            "balances": [dict(balance) for balance in entry.balances],
            "updated_at": entry.updated_at,
        }
        if error:
            result["error"] = error
        return result

    @staticmethod
    def _unavailable(provider: str, error: str) -> dict[str, Any]:
        return {
            "ok": True,
            "provider": provider,
            "state": "unavailable",
            "balances": [],
            "updated_at": None,
            "error": error,
        }
