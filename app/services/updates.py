"""Discover and verify the official stable Windows installer."""

import asyncio
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Callable

import httpx

from app.version import windows_version


RELEASE_PAGE_URL = "https://github.com/heeetz/heetkit-bot/releases/latest"
LATEST_RELEASE_API_URL = "https://api.github.com/repos/heeetz/heetkit-bot/releases/latest"
RELEASE_DOWNLOAD_URL = "https://github.com/heeetz/heetkit-bot/releases/download"
UPDATE_CHECK_TIMEOUT_SECONDS = 10.0
MAX_RESPONSE_BYTES = 256 * 1024
MAX_INSTALLER_BYTES = 512 * 1024 * 1024
DOWNLOAD_TIMEOUT_SECONDS = 900
PUBLISHER_KEY = Path(__file__).resolve().parents[1] / "resources" / "update-publisher.pub"
_VERSION_RE = re.compile(r"v?(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})")
_INVALID_RESPONSE = "GitHub returned invalid stable release information. Try again later."


class UpdateCheckError(RuntimeError):
    """An update check failed with a safe, user-facing explanation."""


@dataclass(frozen=True)
class ReleaseAssets:
    version: str
    tag: str
    size: int
    digest: str | None

    @property
    def name(self) -> str:
        return f"HeetKit-{self.version}-windows-x64-setup.exe"

    def url(self, suffix: str = "") -> str:
        return f"{RELEASE_DOWNLOAD_URL}/{self.tag}/{self.name}{suffix}"


@dataclass(frozen=True)
class VerifiedUpdate:
    assets: ReleaseAssets
    manifest: bytes
    signature: bytes
    sha256: str


def select_installer(payload: dict, version: str) -> ReleaseAssets | None:
    files = payload.get("assets")
    if not isinstance(files, list):
        return None
    name = f"HeetKit-{version}-windows-x64-setup.exe"
    tag = payload["tag_name"]
    selected = {}
    for suffix in ("", ".manifest.json", ".manifest.sig"):
        filename = name + suffix
        matches = [asset for asset in files if isinstance(asset, dict) and asset.get("name") == filename]
        if len(matches) != 1:
            return None
        asset = matches[0]
        if (asset.get("state") != "uploaded"
                or asset.get("browser_download_url") != f"{RELEASE_DOWNLOAD_URL}/{tag}/{filename}"):
            return None
        selected[suffix] = asset
    size = selected[""].get("size")
    digest = selected[""].get("digest")
    if type(size) is not int or not 0 < size <= MAX_INSTALLER_BYTES:
        return None
    if digest is not None and (not isinstance(digest, str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", digest)):
        return None
    return ReleaseAssets(version, tag, size, digest)


def publisher_key() -> bytes | None:
    try:
        with PUBLISHER_KEY.open("rb") as source:
            raw = source.read(67)
        return bytes.fromhex(raw.decode("ascii")) if re.fullmatch(rb"[a-fA-F0-9]{64}(?:\r?\n)?", raw) else None
    except (OSError, ValueError):
        return None


def verify_manifest(assets: ReleaseAssets, manifest: bytes, signature: bytes, key: bytes) -> VerifiedUpdate:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    try:
        Ed25519PublicKey.from_public_bytes(key).verify(signature, manifest)
        data = json.loads(manifest)
    except (InvalidSignature, ValueError, RecursionError) as error:
        raise UpdateCheckError("The release manifest failed publisher verification.") from error
    if (not isinstance(data, dict) or set(data) != {"version", "asset", "size", "sha256"}
            or data["version"] != assets.version or data["asset"] != assets.name
            or type(data["size"]) is not int or data["size"] != assets.size
            or not isinstance(data["sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", data["sha256"])
            or (assets.digest is not None and assets.digest != "sha256:" + data["sha256"])):
        raise UpdateCheckError("The signed release manifest does not match the Windows installer.")
    return VerifiedUpdate(assets, manifest, signature, data["sha256"])


async def _download(client: httpx.AsyncClient, url: str, limit: int, write: Callable[[bytes], object]) -> int:
    # Follow only the release CDN redirect. Keep headers free of profile/auth data.
    for attempt in range(2):
        async with client.stream("GET", url, auth=None, follow_redirects=False, timeout=20.0,
                                 headers={"Accept-Encoding": "identity", "User-Agent": "HeetKit-updater"}) as response:
            if attempt == 0 and response.is_redirect:
                try:
                    redirect = httpx.URL(response.headers.get("Location", ""))
                except httpx.InvalidURL:
                    break
                if (redirect.scheme != "https" or redirect.host != "release-assets.githubusercontent.com"
                        or redirect.port is not None or redirect.userinfo):
                    break
                url = str(redirect)
                continue
            if response.status_code != 200 or response.headers.get("Content-Encoding", "identity") != "identity":
                break
            size = 0
            async for chunk in response.aiter_bytes(chunk_size=256 * 1024):
                size += len(chunk)
                if size > limit:
                    raise UpdateCheckError("A release download exceeded its expected size.")
                write(chunk)
            return size
    raise UpdateCheckError("The release files could not be downloaded from GitHub.")


async def authorize_installer(client: httpx.AsyncClient, assets: ReleaseAssets, key: bytes) -> VerifiedUpdate:
    manifest, signature = bytearray(), bytearray()
    try:
        async with asyncio.timeout(10):
            await _download(client, assets.url(".manifest.json"), 4096, manifest.extend)
            await _download(client, assets.url(".manifest.sig"), 64, signature.extend)
    except (TimeoutError, httpx.HTTPError) as error:
        raise UpdateCheckError("Could not download the signed release manifest.") from error
    return verify_manifest(assets, bytes(manifest), bytes(signature), key)


def verify_installer_file(path: Path, update: VerifiedUpdate) -> None:
    if path.is_symlink() or path.is_junction():
        raise UpdateCheckError("The downloaded installer is a linked file.")
    with path.open("rb") as source:
        if path.stat().st_size != update.assets.size or hashlib.file_digest(source, "sha256").hexdigest() != update.sha256:
            raise UpdateCheckError("The downloaded installer failed size or SHA-256 verification.")


async def download_installer(client: httpx.AsyncClient, update: VerifiedUpdate, path: Path,
                             progress: Callable[[str, int], None]) -> None:
    size = 0
    try:
        with path.open("xb") as output:
            def write(chunk: bytes) -> None:
                nonlocal size
                output.write(chunk)
                size += len(chunk)
                progress("downloading", size)

            progress("downloading", 0)
            async with asyncio.timeout(DOWNLOAD_TIMEOUT_SECONDS):
                await _download(client, update.assets.url(), update.assets.size, write)
        progress("verifying", size)
        verify_installer_file(path, update)
    except (TimeoutError, httpx.HTTPError, OSError) as error:
        raise UpdateCheckError("The installer download was interrupted. Check your connection and free disk space, then retry.") from error


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
    try:
        current_parts = windows_version(current_version)
        candidate = windows_version(latest_version)
        if candidate[0] == 0:
            raise ValueError("Pre-1.0 releases are prereleases.")
    except ValueError as error:
        raise UpdateCheckError(_INVALID_RESPONSE) from error
    result = {
        "latest_version": latest_version,
        "update_available": candidate > current_parts,
        "release_name": _summary(payload.get("name"), 120) or f"HeetKit {latest_version}",
        "release_notes": _summary(payload.get("body"), 600),
        "published_at": published_at,
    }
    if candidate > current_parts and (assets := select_installer(payload, latest_version)) is not None:
        result["_installer"] = assets
    return result


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
