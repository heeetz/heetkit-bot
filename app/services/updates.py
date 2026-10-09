"""Manual, unauthenticated discovery of the official stable desktop release."""

import asyncio
from datetime import datetime
import json
import re

import httpx


RELEASE_PAGE_URL = "https://github.com/heeetz/heetkit-bot/releases/latest"
LATEST_RELEASE_API_URL = "https://api.github.com/repos/heeetz/heetkit-bot/releases/latest"
UPDATE_CHECK_TIMEOUT_SECONDS = 10.0
MAX_RESPONSE_BYTES = 256 * 1024
_VERSION_RE = re.compile(r"v?(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})")
_INVALID_RESPONSE = "GitHub returned invalid stable release information. Try again later."


class UpdateCheckError(RuntimeError):
    """An update check failed with a safe, user-facing explanation."""


def _version_parts(value: object) -> tuple[int, int, int]:
    match = _VERSION_RE.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise UpdateCheckError(_INVALID_RESPONSE)
    return tuple(int(part) for part in match.groups())


def _summary(value: object, limit: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise UpdateCheckError(_INVALID_RESPONSE)
    text = value.strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _release_info(payload: object, current_version: str) -> dict[str, object]:
    if not isinstance(payload, dict) or payload.get("draft") is not False or payload.get("prerelease") is not False:
        raise UpdateCheckError(_INVALID_RESPONSE)
    latest_parts = _version_parts(payload.get("tag_name"))
    published_at = payload.get("published_at")
    if not isinstance(published_at, str) or len(published_at) > 40:
        raise UpdateCheckError(_INVALID_RESPONSE)
    try:
        published = datetime.fromisoformat(published_at)
    except ValueError as error:
        raise UpdateCheckError(_INVALID_RESPONSE) from error
    if published.tzinfo is None:
        raise UpdateCheckError(_INVALID_RESPONSE)
    latest_version = ".".join(str(part) for part in latest_parts)
    return {
        "latest_version": latest_version,
        "update_available": latest_parts > _version_parts(current_version),
        "release_name": _summary(payload.get("name"), 120) or f"HeetKit {latest_version}",
        "release_notes": _summary(payload.get("body"), 600),
        "published_at": published_at,
    }


async def check_for_updates(client: httpx.AsyncClient, current_version: str) -> dict[str, object]:
    """Use the application's existing client without credentials, retries or state writes."""
    try:
        async with asyncio.timeout(UPDATE_CHECK_TIMEOUT_SECONDS):
            async with client.stream(
                "GET", LATEST_RELEASE_API_URL,
                headers={
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2026-03-10",
                    "User-Agent": "HeetKit-update-check",
                },
                auth=None, follow_redirects=False, timeout=8.0,
            ) as response:
                if response.status_code in {403, 429}:
                    raise UpdateCheckError("GitHub update checks are temporarily limited. Try again later.")
                if response.status_code == 404:
                    raise UpdateCheckError("No stable release is currently available. Try again later.")
                if response.status_code != 200:
                    raise UpdateCheckError("GitHub release information is unavailable. Try again later.")
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > MAX_RESPONSE_BYTES:
                        raise UpdateCheckError(_INVALID_RESPONSE)
                try:
                    payload = json.loads(content)
                except (ValueError, UnicodeDecodeError, RecursionError) as error:
                    raise UpdateCheckError(_INVALID_RESPONSE) from error
                return _release_info(payload, current_version)
    except (TimeoutError, httpx.TimeoutException) as error:
        raise UpdateCheckError("The update check timed out. Try again.") from error
    except httpx.RequestError as error:
        raise UpdateCheckError("Could not reach GitHub. Check your internet connection and try again.") from error
