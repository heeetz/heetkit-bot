"""Stable release discovery with synthetic public GitHub responses."""

import asyncio

import httpx
import pytest

from app.services.updates import (
    LATEST_RELEASE_API_URL, MAX_RESPONSE_BYTES, UpdateCheckError, check_for_updates,
)


def release(**overrides) -> dict:
    return {
        "tag_name": "v1.0.0", "draft": False, "prerelease": False,
        "name": "HeetKit 1.0.0", "body": "A stable desktop release.",
        "published_at": "2026-10-05T12:00:00Z", **overrides,
    }


@pytest.mark.parametrize(("current", "latest", "newer"), [
    ("1.0.0", "v1.0.0", False), ("1.1.0", "v1.0.0", False),
    ("1.0.0", "v1.0.1", True), ("1.9.0", "v1.10.0", True),
    ("9.0.0", "v10.0.0", True), ("1.0.9", "1.0.10", True),
    ("2.0.0", "v1.99.99", False),
])
async def test_numeric_stable_version_comparison_and_public_request(current, latest, newer) -> None:
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=release(tag_name=latest))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), auth=("unused", "synthetic")) as client:
        result = await check_for_updates(client, current)
        assert not client.is_closed

    assert result["latest_version"] == latest.removeprefix("v")
    assert result["update_available"] is newer
    assert result["release_name"] == "HeetKit 1.0.0"
    assert result["release_notes"] == "A stable desktop release."
    assert result["published_at"] == "2026-10-05T12:00:00Z"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "GET"
    assert str(request.url) == LATEST_RELEASE_API_URL
    assert "authorization" not in request.headers
    assert request.headers["accept"] == "application/vnd.github+json"
    assert request.headers["x-github-api-version"] == "2026-03-10"
    assert request.headers["user-agent"] == "HeetKit-update-check"
    assert all(value == 8.0 for value in request.extensions["timeout"].values())


@pytest.mark.parametrize("payload", [
    None, [], "release", {}, release(draft=True), release(prerelease=True),
    release(draft=0), release(prerelease=None),
    release(tag_name="v2.0.0-rc.1"), release(tag_name="v2.0.0+build"),
    release(tag_name="v01.0.0"), release(tag_name="2.0"), release(tag_name=3),
    release(tag_name="v9999999999.0.0"), release(tag_name=" v2.0.0"),
    release(name=[]), release(body={}), release(published_at=None),
    release(published_at="not a date"), release(published_at="2026-10-05"),
])
async def test_malformed_or_nonstable_release_is_rejected(payload) -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))) as client:
        with pytest.raises(UpdateCheckError, match="invalid stable release information"):
            await check_for_updates(client, "1.0.0")


@pytest.mark.parametrize("content", [b"<html>unavailable</html>", b"{", b"\xff", b"x" * (MAX_RESPONSE_BYTES + 1)],
                         ids=["html", "truncated-json", "non-utf8", "oversized"])
async def test_malformed_or_oversized_body_is_rejected(content) -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=content))) as client:
        with pytest.raises(UpdateCheckError, match="invalid stable release information"):
            await check_for_updates(client, "1.0.0")


@pytest.mark.parametrize(("status", "message"), [
    (403, "temporarily limited"), (429, "temporarily limited"),
    (404, "No stable release"), (500, "unavailable"), (503, "unavailable"),
    (204, "unavailable"), (302, "unavailable"),
])
async def test_http_failures_do_not_retry_or_follow_external_redirects(status, message) -> None:
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status, headers={"Location": "https://attacker.test/installer.exe"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
        with pytest.raises(UpdateCheckError, match=message):
            await check_for_updates(client, "1.0.0")
    assert len(requests) == 1


@pytest.mark.parametrize(("error_type", "message"), [
    (httpx.ConnectError, "Could not reach GitHub"),
    (httpx.ReadTimeout, "timed out"), (httpx.ConnectTimeout, "timed out"),
])
async def test_network_errors_have_safe_retry_messages(error_type, message) -> None:
    def handler(request):
        raise error_type("private transport details", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(UpdateCheckError, match=message) as captured:
            await check_for_updates(client, "1.0.0")
    assert "private" not in str(captured.value)


async def test_total_deadline_bounds_slow_release_response(monkeypatch) -> None:
    async def handler(request):
        await asyncio.sleep(1)
        return httpx.Response(200, json=release())

    monkeypatch.setattr("app.services.updates.UPDATE_CHECK_TIMEOUT_SECONDS", 0.01)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(UpdateCheckError, match="timed out"):
            await check_for_updates(client, "1.0.0")


async def test_each_manual_check_is_fresh_and_summary_is_bounded_plain_text() -> None:
    responses = [
        release(tag_name="v1.1.0", name="Title" * 100, body="<script>never execute</script>\n" + "x" * 1000,
                html_url="https://attacker.test/installer.exe"),
        release(tag_name="v1.2.0", name=None, body=None),
    ]
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=responses.pop(0)))) as client:
        first = await check_for_updates(client, "1.0.0")
        second = await check_for_updates(client, "1.0.0")
    assert len(first["release_name"]) == 120
    assert len(first["release_notes"]) == 600
    assert first["release_notes"].startswith("<script>never execute</script>\n")
    assert first["release_notes"].endswith("…")
    assert "html_url" not in first
    assert second["latest_version"] == "1.2.0"
    assert second["release_name"] == "HeetKit 1.2.0"
    assert second["release_notes"] == ""
