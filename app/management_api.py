"""Opt-in private, single-administrator HTTP transport for the shared core."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import inspect
import ipaddress
import json
import logging
import os
import re
import secrets
import stat
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from aiohttp import web

from app.app_settings import AppSettingsStore
from app.bot_runtime import BotRuntime
from app.operation_policy import OperationPolicy
from app.configuration_transfer import MAX_TRANSFER_BODY
from app.management import ApplicationManagement
from app.runtime_paths import PACKAGED_FRONTEND, SOURCE_ROOT, RuntimePaths
from app.utils.logging import RecentLogBuffer
from app.credentials import CredentialError
from app.config.settings import TwitchConfigurationError
from app.server_setup import ServerSetup


MAX_BODY = 65536
REQUEST_SECONDS = 25
CONNECTION_SECONDS = 35
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{43,128}\Z")
SESSION_SECONDS = 3600
MAX_SESSIONS = 8
MAX_ASSET = 4 * 1024 * 1024


@dataclass(frozen=True)
class ManagementConfig:
    token: str = field(repr=False)
    host: str = "127.0.0.1"
    port: int = 8765
    allowed_host: str | None = None
    trusted_origin: str | None = None
    trusted_proxies: tuple[str, ...] = ()
    twitch_redirect_uri: str | None = None

    def __post_init__(self) -> None:
        address = ipaddress.ip_address(self.host)
        if not (address.is_loopback or address.is_private or address.is_unspecified) or address.is_multicast:
            raise ValueError("Management must bind to loopback or a trusted private interface.")
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ValueError("Management port must be between 1 and 65535.")
        if not TOKEN_PATTERN.fullmatch(self.token):
            raise ValueError("Management token must be 43-128 URL-safe characters; generate at least 32 random bytes.")
        if self.allowed_host is not None:
            # An exact literal authority, never a wildcard, URL, proxy header or DNS suffix.
            match = re.fullmatch(r"(\[[0-9a-fA-F:]+\]|[0-9.]+):([0-9]{1,5})", self.allowed_host)
            if match is None or not 1 <= int(match[2]) <= 65535:
                raise ValueError("Management allowed host must be an exact IP:port authority.")
            ipaddress.ip_address(match[1].strip("[]"))
        if self.trusted_origin is not None:
            # Canonical ASCII DNS origin, with an optional non-default port. No
            # credentials, paths, wildcard/suffix matching or URL normalization.
            origin = self.trusted_origin
            match = re.fullmatch(r"https://([a-z0-9.-]+)(?::([0-9]{1,5}))?", origin)
            if match is None or len(match[1]) > 253 or "." not in match[1]:
                raise ValueError("Trusted origin must be an exact lowercase HTTPS DNS origin without a path.")
            if any(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) is None
                   for label in match[1].split(".")) or match[1].replace(".", "").isdigit():
                raise ValueError("Trusted origin must contain a valid DNS hostname.")
            if match[2] is not None and (not 1 <= int(match[2]) <= 65535
                    or match[2] != str(int(match[2])) or int(match[2]) == 443):
                raise ValueError("Trusted origin port must be canonical; omit the default HTTPS port.")
            if self.allowed_host is not None or not self.trusted_proxies:
                raise ValueError("HTTPS proxy mode requires trusted proxy IPs and replaces allowed-host.")
        elif self.trusted_proxies or self.twitch_redirect_uri is not None:
            raise ValueError("Trusted proxies and a remote callback require an explicit trusted HTTPS origin.")
        for proxy in self.trusted_proxies:
            peer = ipaddress.ip_address(proxy)
            if peer.is_unspecified or peer.is_multicast or str(peer) != proxy:
                raise ValueError("Trusted proxies must be exact canonical IPs, never networks or wildcard addresses.")
        if self.twitch_redirect_uri is not None and self.twitch_redirect_uri != self.trusted_origin + "/oauth/callback":
            raise ValueError("Twitch redirect must be the trusted HTTPS origin followed by /oauth/callback.")
        if address.is_unspecified and self.allowed_host is None and self.trusted_origin is None:
            raise ValueError("An all-interface bind requires an explicit management allowed host.")

    @property
    def authorities(self) -> set[str]:
        if self.trusted_origin:
            return {urlsplit(self.trusted_origin).netloc}
        if self.allowed_host:
            return {self.allowed_host}
        authority = f"[{self.host}]:{self.port}" if ":" in self.host else f"{self.host}:{self.port}"
        return {authority, f"localhost:{self.port}"} if ipaddress.ip_address(self.host).is_loopback else {authority}

    @property
    def oauth_redirect_uri(self) -> str:
        # Twitch supports HTTP localhost redirects. Use the published management
        # port, never Desktop's listener or a request/forwarding header.
        port = self.allowed_host.rsplit(":", 1)[1] if self.allowed_host else self.port
        return self.twitch_redirect_uri or f"http://localhost:{port}/oauth/callback"

    @property
    def oauth_callback_enabled(self) -> bool:
        if self.trusted_origin:
            return self.twitch_redirect_uri is not None
        address = self.allowed_host.rsplit(":", 1)[0].strip("[]") if self.allowed_host else self.host
        # Other loopbacks/private addresses cannot be reached via localhost.
        # Keep authenticated paste completion for those installations.
        return address in ("127.0.0.1", "::1")

    def accepts_proxy(self, request: web.BaseRequest) -> bool:
        forwarded = {name.lower() for name in request.headers
                     if name.lower() == "forwarded" or name.lower().startswith("x-forwarded-")}
        if not self.trusted_origin:
            return not forwarded
        # Peer identity comes from the socket, never a forwarding header. Proxies
        # must overwrite these headers and preserve the original exact Host.
        if request.remote not in self.trusted_proxies or forwarded - {
                "x-forwarded-proto", "x-forwarded-host", "x-forwarded-for"}:
            return False
        if request.headers.getall("X-Forwarded-Proto", []) != ["https"]:
            return False
        hosts = request.headers.getall("X-Forwarded-Host", [])
        if hosts and hosts != [urlsplit(self.trusted_origin).netloc]:
            return False
        clients = request.headers.getall("X-Forwarded-For", [])
        if clients:
            try:
                if len(clients) != 1:
                    return False
                ipaddress.ip_address(clients[0])
            except ValueError:
                return False
        return True


def load_management_token() -> str:
    """No command-line secret, keyring, generated fallback or secret logging."""
    token = os.environ.get("HEETKIT_MANAGEMENT_TOKEN", "").strip()
    filename = os.environ.get("HEETKIT_MANAGEMENT_TOKEN_FILE")
    if filename:
        if token:
            raise ValueError("Set only HEETKIT_MANAGEMENT_TOKEN or HEETKIT_MANAGEMENT_TOKEN_FILE.")
        try:
            descriptor = os.open(filename, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
            with os.fdopen(descriptor, "rb") as source:
                if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                    raise ValueError
                raw = source.read(1025)
            if len(raw) > 1024:
                raise ValueError
            token = raw.decode("ascii").strip()
        except (OSError, ValueError):
            raise ValueError("Cannot read management token file; use a private regular ASCII file of at most 1 KiB.") from None
    if not TOKEN_PATTERN.fullmatch(token):
        raise ValueError("Supply a private management token generated from at least 32 random bytes (43-128 URL-safe characters).")
    return token


# Explicit transport contract. These operations cannot traverse Python attributes,
# credentials, local paths, desktop actions, provider clients or the pywebview bridge.
READS = {
    "/v1/status": "get_app_status",
    "/v1/commands": "get_commands",
    "/v1/custom-commands": "get_custom_commands",
    "/v1/filters": "get_filters",
    "/v1/ai": "get_ai_status",
    "/v1/ai/models": "get_ai_provider_settings",
    "/v1/ai/language": "get_ai_language_settings",
    "/v1/personalities": "get_personalities",
    "/v1/blocked-users": "get_blocked_ai_users",
}
WRITES = {
    "/v1/configuration/export": "export_configuration",
    "/v1/configuration/preview": "preview_configuration_import",
    "/v1/configuration/import": "apply_configuration_import",
    "/v1/commands/apply": "apply_command_settings",
    "/v1/commands/reset-all": "reset_all_builtin_commands",
    "/v1/commands/save": "save_command_settings",
    "/v1/commands/reset": "reset_command_settings",
    "/v1/commands/remove": "remove_builtin_command",
    "/v1/commands/restore": "restore_builtin_command",
    "/v1/commands/responses/save": "save_command_responses",
    "/v1/commands/responses/apply": "apply_command_responses",
    "/v1/commands/responses/reset": "reset_command_responses",
    "/v1/custom-commands/save": "save_custom_command",
    "/v1/custom-commands/delete": "delete_custom_command",
    "/v1/ai/enabled": "set_ai_enabled",
    "/v1/ai/memory": "_save_ai_memory_enabled",
    "/v1/ai/models": "_save_ai_provider_models",
    "/v1/ai/language": "_save_ai_response_language",
    "/v1/personalities/create": "create_personality",
    "/v1/personalities/rename": "rename_personality",
    "/v1/personalities/delete": "delete_personality",
    "/v1/personalities/activate": "set_active_personality",
    "/v1/personalities/save": "save_personality",
    "/v1/personalities/apply": "apply_personality",
    "/v1/personalities/reset": "reset_personality",
    "/v1/ai/instructions/save": "save_profile_instructions",
    "/v1/ai/instructions/apply": "apply_profile_instructions",
    "/v1/ai/instructions/reset": "reset_profile_instructions",
    "/v1/blocked-users/block": "_block_ai_user",
    "/v1/blocked-users/unblock": "unblock_ai_user",
}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key.")
        result[key] = value
    return result


def _invalid_constant(_value):
    raise ValueError("Non-finite JSON number.")


class ManagementAPI:
    def __init__(self, runtime: BotRuntime, config: ManagementConfig,
                 log_buffer: RecentLogBuffer | None = None, *, policy: OperationPolicy | None = None,
                 app_settings: AppSettingsStore | None = None, credentials=None) -> None:
        self.runtime = runtime
        self.config = config
        store = app_settings or AppSettingsStore(RuntimePaths.default().app_settings)
        self.service = ApplicationManagement(runtime.application, store, log_buffer)
        self.policy = policy or OperationPolicy(runtime, store)
        self.setup = ServerSetup(runtime, self.policy, store, credentials,
            redirect_uri=config.oauth_redirect_uri,
            owner_active=self.owner_active)
        self._owns_policy = policy is None
        self.lock = asyncio.Lock()
        self.runner: web.ServerRunner | None = None
        self.site: web.TCPSite | None = None
        self.active = 0
        self.requests: deque[float] = deque()
        self.started = time.monotonic()
        self.log_buffer = log_buffer
        # Store only digests of short-lived browser bearer tokens. No cookies,
        # persistent session state or automatic renewal of administrator authority.
        self.sessions: dict[bytes, float] = {}
        self.frontend = (SOURCE_ROOT / "frontend" / "dist" if SOURCE_ROOT is not None
                         and not PACKAGED_FRONTEND.is_file() else PACKAGED_FRONTEND.parent)

    async def start(self) -> None:
        # No raw URL/header/error/access records enter the diagnostic buffer.
        quiet = logging.Logger("heetkit.private-http")
        quiet.addHandler(logging.NullHandler())
        server = _BoundedServer(self.handle, access_log=None, logger=quiet,
            debug=False, max_line_size=2048, max_field_size=2048, max_headers=32,
            read_bufsize=8192, auto_decompress=False, keepalive_timeout=2,
            lingering_time=0)
        self.runner = web.ServerRunner(server, shutdown_timeout=2)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, self.config.host, self.config.port, backlog=16)
        try:
            await self.site.start()
            if self._owns_policy:
                await self.policy.start()
        except BaseException:
            await self.close()
            raise

    async def close(self) -> None:
        self.setup.close()
        self.sessions.clear()
        try:
            if self.runner is not None:
                await self.runner.cleanup()
                self.runner = None
        finally:
            if self._owns_policy:
                await self.policy.close()

    def app_status(self) -> dict:
        return self.service.get_app_status() | {"operation": self.policy.snapshot()}

    def owner_active(self, owner: bytes) -> bool:
        administrator = hashlib.sha256(self.config.token.encode("ascii")).digest()
        return hmac.compare_digest(owner, administrator) or self.sessions.get(owner, 0) > time.monotonic()

    async def oauth_callback(self, request: web.BaseRequest) -> web.Response:
        # Never render or reflect query parameters. A fixed clean redirect drops
        # codes/state from the final address and referrer; proxies must omit logs.
        if (request.method != "GET" or request.content_length not in (None, 0)
                or "Transfer-Encoding" in request.headers or "Content-Encoding" in request.headers
                or request.raw_path.split("?", 1)[0] != "/oauth/callback"):
            return self.response(400, {"ok": False, "error": "Invalid OAuth callback."})
        self.active += 1
        try:
            async with asyncio.timeout(REQUEST_SECONDS):
                async with self.lock:
                    await self.setup.callback(request.rel_url.raw_query_string)
        except Exception:
            # Details are visible only as fixed status in the initiating tab.
            # A cancelled/timed-out exchange must never be retried automatically.
            pass
        finally:
            self.active -= 1
        response = self.response(303, {"ok": True})
        response.headers["Location"] = "/oauth/result"
        return response

    @staticmethod
    def response(status: int, payload: dict) -> web.Response:
        encoded = json.dumps(payload, ensure_ascii=True, allow_nan=False)
        if len(encoded) > 2 * 1024 * 1024:
            status, encoded = 500, '{"ok":false,"error":"Response exceeds limit."}'
        response = web.Response(status=status, text=encoded, content_type="application/json",
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                     "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
                     "Referrer-Policy": "no-referrer"})
        response.force_close()
        return response

    def asset(self, path: str) -> web.Response:
        """Serve only Vite's public entry/icon and compiled JS/CSS, never profiles."""
        if path in ("/", "/index.html"):
            relative, content_type = "index.html", "text/html"
        elif path == "/icon.png":
            relative, content_type = "icon.png", "image/png"
        elif re.fullmatch(r"/assets/[A-Za-z0-9_-]+\.(js|css)", path):
            relative = path[1:]
            content_type = "text/javascript" if path.endswith(".js") else "text/css"
        else:
            return self.response(404, {"ok": False, "error": "Unknown management resource."})
        target = self.frontend / relative
        try:
            # The asset root is fixed by installation/source discovery, not a
            # request parameter. Refuse symlink components and bounded reads only.
            if any(part.is_symlink() for part in (self.frontend, target.parent, target)):
                raise OSError
            with target.open("rb") as source:
                if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                    raise OSError
                body = source.read(MAX_ASSET + 1)
            if len(body) > MAX_ASSET:
                raise OSError
            if relative == "index.html":
                body = body.replace(b"<head>", b'<head><meta name="heetkit-transport" content="http">', 1)
        except OSError:
            return self.response(503, {"ok": False, "error": "Browser panel assets unavailable; build the frontend before starting management."})
        response = web.Response(body=body, content_type=content_type, headers={
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self'; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
            "Referrer-Policy": "no-referrer", "Cross-Origin-Resource-Policy": "same-origin",
            "X-Frame-Options": "DENY",
        })
        response.force_close()
        return response

    async def handle(self, request: web.BaseRequest) -> web.Response:
        def reject(status, message):
            return self.response(status, {"ok": False, "error": message})
        now = time.monotonic()
        while self.requests and now - self.requests[0] >= 60:
            self.requests.popleft()
        if len(self.requests) >= 120 or self.active >= 16:
            return reject(429, "Management request limit reached.")
        self.requests.append(now)
        oauth_navigation = (self.config.oauth_callback_enabled
            and request.path in ("/oauth/callback", "/oauth/result")
            and request.headers.get("Host") == urlsplit(self.config.oauth_redirect_uri).netloc)
        if (len(request.headers.getall("Host", [])) != 1 or
                (request.headers.get("Host") not in self.config.authorities and not oauth_navigation)):
            return reject(403, "Untrusted Host.")
        if not self.config.accepts_proxy(request):
            return reject(403, "Untrusted proxy headers or peer; check the configured HTTPS proxy boundary.")
        origins = request.headers.getall("Origin", [])
        host = request.headers["Host"]
        allowed_origins = {self.config.trusted_origin or "https://" + host}
        if not self.config.trusted_origin:
            origin_host = host.rsplit(":", 1)[0].strip("[]")
            if origin_host == "localhost" or ipaddress.ip_address(origin_host).is_loopback:
                allowed_origins.add("http://" + host)
        callback = oauth_navigation and request.path == "/oauth/callback"
        # Fetch Metadata can remain cross-site through Twitch's entire redirect
        # chain. Its final fixed, inert result page must allow that navigation too.
        # Unrelated local services can set cookies on this host across ports.
        # Ignore them: only the explicit bearer below can grant authority.
        if (len(origins) > 1 or (origins and origins[0] not in allowed_origins)
                or (not oauth_navigation and request.headers.get("Sec-Fetch-Site", "none") not in ("none", "same-origin"))):
            return reject(403, "Untrusted browser origin.")
        if callback:
            return await self.oauth_callback(request)
        if request.query_string or request.raw_path != request.path:
            return reject(400, "Use an exact path without query parameters.")
        if request.method not in ("GET", "POST"):
            return reject(405, "Method not supported.")
        if not request.path.startswith("/v1/"):
            if request.method != "GET" or request.content_length not in (None, 0):
                return reject(405, "Assets require GET without a body.")
            if request.path == "/oauth/result" and oauth_navigation:
                response = self.response(200, {})
                response.text = "Twitch authorization attempt finished. Close this tab and return to the signed-in Settings tab for the result. If it is still waiting, check callback reachability, registered redirect and proxy settings, then try again."
                response.content_type = "text/plain"
                return response
            return self.asset(request.path)
        authorization = request.headers.getall("Authorization", [])
        expected = "Bearer " + self.config.token
        self.sessions = {key: expiry for key, expiry in self.sessions.items() if expiry > now}
        supplied = authorization[0] if len(authorization) == 1 else ""
        admin = hmac.compare_digest(supplied.encode("utf-8"), expected.encode("ascii"))
        digest = hashlib.sha256(supplied.removeprefix("Bearer ").encode("utf-8")).digest()
        session = supplied.startswith("Bearer ") and digest in self.sessions
        if not (admin or session):
            return reject(401, "Authentication required.")
        if request.path == "/v1/session" and (admin != (request.method == "POST")):
            return reject(401, "Authentication required.")
        if "Content-Encoding" in request.headers or "Transfer-Encoding" in request.headers:
            return reject(400, "Encoded or streamed bodies are not supported.")
        self.active += 1
        try:
            async with asyncio.timeout(REQUEST_SECONDS):
                payload = {}
                if request.method == "POST":
                    if request.content_type != "application/json":
                        return reject(415, "Use application/json.")
                    length = request.content_length
                    maximum = MAX_TRANSFER_BODY if request.path in (
                        "/v1/configuration/preview", "/v1/configuration/import") else MAX_BODY
                    if length is None or length < 2 or length > maximum:
                        return reject(413, "JSON body exceeds this operation's size limit.")
                    async with asyncio.timeout(5):
                        raw = await request.content.readexactly(length)
                    payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                                         parse_constant=_invalid_constant)
                    if not isinstance(payload, dict):
                        return reject(400, "JSON body must be an object.")
                elif request.content_length not in (None, 0):
                    return reject(400, "GET does not accept a body.")
                # The lock spans awaited lifecycle/block operations as well as
                # synchronous store transactions. All mutations run on the core loop.
                async with self.lock:
                    # A queued request must not outlive logout/session expiry.
                    if session and self.sessions.get(digest, 0) <= time.monotonic():
                        return reject(401, "Session expired; sign in again.")
                    if request.path == "/v1/session":
                        if payload:
                            raise ValueError
                        result = {"ok": True}
                        if request.method == "POST":
                            token = secrets.token_urlsafe(32)
                            if len(self.sessions) >= MAX_SESSIONS:
                                self.setup.cancel(next(iter(self.sessions)))
                                del self.sessions[next(iter(self.sessions))]
                            self.sessions[hashlib.sha256(token.encode("ascii")).digest()] = now + SESSION_SECONDS
                            result.update(token=token, expires_in=SESSION_SECONDS)
                    elif request.method == "POST" and request.path == "/v1/session/logout":
                        if payload:
                            raise ValueError
                        self.sessions.pop(digest, None)
                        self.setup.cancel(digest)
                        result = {"ok": True}
                    else:
                        result = await self.dispatch(request.method, request.path, payload, owner=digest)
                status = 200 if result.get("ok", True) else 400
                return self.response(status, result)
        except TimeoutError:
            return reject(504, "Management operation timed out; inspect current state before retrying.")
        except LookupError:
            return reject(404, "Unknown management resource.")
        except (CredentialError, TwitchConfigurationError) as error:
            return reject(400, str(error))
        except (ValueError, TypeError, RecursionError, UnicodeError, asyncio.IncompleteReadError):
            return reject(400, "Invalid management input.")
        except Exception:
            # Domain errors may contain provider secrets or paths; never serialize
            # exception strings/tracebacks, even for authenticated administrators.
            return reject(500, "Management operation failed; check private profile storage and connection state.")
        finally:
            self.active -= 1

    async def dispatch(self, method: str, path: str, payload: dict, *, owner: bytes = b"") -> dict:
        if method == "POST" and path.startswith(("/v1/credentials/", "/v1/twitch/")):
            operations = {
                "/v1/twitch/settings": self.setup.save_twitch,
                "/v1/twitch/presets/save": self.setup.save_preset,
                "/v1/twitch/presets/delete": self.setup.delete_preset,
                "/v1/twitch/presets/switch": self.setup.switch_preset,
                "/v1/credentials/replace": self.setup.change_credential,
                "/v1/credentials/remove": lambda name: self.setup.change_credential(name, remove=True),
                "/v1/credentials/test": self.setup.test_credential,
                "/v1/twitch/authorization/begin": lambda: self.setup.begin(owner),
                "/v1/twitch/authorization/complete": lambda callback_url: self.setup.complete(owner, callback_url),
                "/v1/twitch/authorization/cancel": lambda: self.setup.cancel(owner),
            }
            operation = operations.get(path)
            if operation is None:
                raise LookupError
            # Fixed fields, including replace's required value: no caller may
            # smuggle the internal remove flag through a different endpoint.
            fields = {"/v1/twitch/settings": {"client_id", "bot_username", "bot_user_id", "channel", "channel_user_id"},
                "/v1/twitch/presets/save": {"preset_id", "display_name", "channel", "channel_user_id"},
                "/v1/twitch/presets/delete": {"preset_id"}, "/v1/twitch/presets/switch": {"preset_id"},
                "/v1/credentials/replace": {"name", "value"}, "/v1/credentials/remove": {"name"},
                "/v1/credentials/test": {"name"}, "/v1/twitch/authorization/complete": {"callback_url"}}
            if set(payload) != fields.get(path, set()):
                raise ValueError
            result = operation(**payload)
            return await result if inspect.isawaitable(result) else result
        operations = READS if method == "GET" else WRITES
        if path in operations:
            operation = getattr(self.service, operations[path])
            inspect.signature(operation).bind(**payload)
            result = operation(**payload)
            if inspect.isawaitable(result):
                result = await result
            if not isinstance(result, dict):
                result = {"ok": True}
            # Domain validators remain authoritative; never echo their exception
            # text (some legacy validators interpolate supplied values).
            if result.get("ok") is False:
                return {"ok": False, "error": "Operation rejected; check input, profile storage and current state."}
            if method == "POST":
                self.policy.refresh_command_monitoring()
            if method == "GET" and path == "/v1/ai/models":
                result["settings"]["credential"] = self.ai_credential_status(result["settings"]["provider_id"])
            if method == "GET" and path == "/v1/status":
                result["operation"] = self.policy.snapshot()
            return result
        if method == "GET" and path == "/v1/snapshot":
            return {"status": self.app_status(), "ai_status": self.service.get_ai_status()}
        if method == "GET" and path == "/v1/about":
            return self.service.get_about_info()
        if method == "GET" and path == "/v1/setup":
            return self.setup_status(owner)
        if method == "POST" and path == "/v1/ai/models/discover":
            from app.config.ai_models import validate_ai_provider
            from app.services.ai_provider import AIModelDiscoveryError
            if set(payload) - {"provider"}:
                raise ValueError
            provider = validate_ai_provider(payload.get("provider", self.runtime.application.settings.ai_provider))
            try:
                models = await self.runtime.application.services.ai.discover_models(provider)
            except AIModelDiscoveryError as error:
                return {"ok": False, "error": str(error), "error_code": error.code, "provider_id": provider}
            return {"ok": True, "models": models, "provider_id": provider}
        if method == "GET" and path == "/v1/diagnostics":
            return {"ok": True, "process_uptime_seconds": int(time.monotonic() - self.started),
                    "desired_running": self.policy.desired_running, "operation": self.policy.snapshot(),
                    "settings_effect": {"commands_filters_ai_personalities_triggers": "immediate",
                        "twitch_target": "save and reconnect",
                        "twitch_identity_secret": "save, authorize and reconnect",
                        "gemini_key": "immediate",
                        "deepseek_key": "immediate",
                        "privacy_api_bind": "process_restart (configure outside API)"}}
        if method == "POST" and path in ("/v1/bot/start", "/v1/bot/stop"):
            if payload:
                raise ValueError
            if path.endswith("/start"):
                self.setup.require_ready()
            changed = self.policy.connect() if path.endswith("/start") else self.policy.disconnect()
            return {"ok": True, "changed": changed, "operation": self.policy.snapshot()}
        if method == "POST" and path == "/v1/bot/mode":
            if set(payload) != {"mode"}:
                raise ValueError
            changed = self.policy.set_mode(payload["mode"])
            return {"ok": True, "changed": changed, "operation": self.policy.snapshot()}
        if method == "POST" and path in ("/v1/filters/save", "/v1/filters/apply", "/v1/filters/test"):
            if not path.endswith("/test"):
                if set(payload) != {"payload"}:
                    raise ValueError
                await self.service._change_filters(payload["payload"], save=path.endswith("/save"))
                return {"ok": True}
            operation = self.service._test_filters
            inspect.signature(operation).bind(**payload)
            return await operation(**payload)
        if path == "/v1/triggers":
            store = self.runtime.application.dispatcher._message_triggers
            if method == "POST":
                if set(payload) != {"triggers"}:
                    raise ValueError
                store.save(payload["triggers"])
            return {"ok": True, "triggers": [asdict(trigger) for trigger in store.list()]}
        if method == "POST" and path == "/v1/logs/recent":
            if set(payload) - {"after_id", "limit"}:
                raise ValueError
            after, limit = payload.get("after_id", 0), payload.get("limit", 100)
            if type(after) is not int or after < 0 or type(limit) is not int or not 1 <= limit <= 200:
                raise ValueError
            return {"ok": True, **(self.log_buffer.activity(after_id=after, limit=limit)
                    if self.log_buffer else {"entries": [], "next_after_id": after})}
        raise LookupError

    def credential_statuses(self) -> list[dict]:
        """Presence/source only; never read values back to the browser."""
        return self.setup.credentials.server_statuses()

    def ai_credential_status(self, provider: str) -> dict:
        return next(status for status in self.credential_statuses() if status["name"] == provider + "_api_key")

    def setup_status(self, owner: bytes = b"") -> dict:
        """Project effective configuration status, never credentials or paths."""
        settings = self.runtime.application.settings
        credentials = self.credential_statuses()
        provider = self.service.get_ai_provider_settings()["settings"]
        provider["credential"] = self.ai_credential_status(provider["provider_id"])
        state = self.service.get_app_status()
        self.setup._expire()
        connected = state["twitch_connected"]
        authorization = "verified" if connected else self.setup.authorization_status
        if state["twitch_connection_state"] == "auth_required":
            self.setup.authorization_status = "validation_failed"
            self.setup.authorized_account = None
            authorization = "validation_failed"
        elif self.policy.error and not connected:
            authorization = "not_verified"
        presets = self.setup.store.snapshot().twitch.presets
        active = next((preset.id for preset in presets if preset.channel == settings.twitch_channel
            and preset.channel_user_id == settings.twitch_channel_user_id), None)
        return {"ok": True, "credentials": credentials, "aiProvider": provider,
            "twitch": {"client_id": settings.twitch_client_id, "bot_username": settings.twitch_bot_username,
                "bot_user_id": settings.twitch_bot_user_id, "target_channel": settings.twitch_channel,
                "target_channel_user_id": settings.twitch_channel_user_id,
                "active_channel": settings.twitch_channel, "active_channel_user_id": settings.twitch_channel_user_id,
                "requires_restart": False, "requires_reconnect": False, "running": state["running"],
                "connected": state["twitch_connected"], "oauth_token_available": Path(settings.twitch_token_file).is_file(),
                "presets": [{"id": preset.id, "display_name": preset.display_name,
                    "target_channel": preset.channel, "target_channel_user_id": preset.channel_user_id}
                    for preset in presets], "selected_preset_id": active, "active_preset_id": active,
                "oauth_callback_url": self.setup.redirect_uri, "has_local_override": False,
                "management_url": self.config.trusted_origin or "http://" + sorted(self.config.authorities)[0],
                "authorization_mode": "redirect" if self.config.oauth_callback_enabled else "paste",
                "authorization_attempt": self.setup.attempt_status(owner),
                "authorization_status": authorization,
                "authorized_account": settings.twitch_bot_username if connected else self.setup.authorized_account,
                "setup_complete": authorization == "verified"}}


class _BoundedServer(web.Server):
    """Limit idle/partial HTTP connections before request middleware can run."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.deadlines = {}

    def connection_made(self, handler, transport):
        if len(self.connections) >= 32:
            transport.close()
            return
        super().connection_made(handler, transport)
        # Absolute lifetime also bounds slow headers, bodies and pipelining.
        self.deadlines[handler] = asyncio.get_running_loop().call_later(CONNECTION_SECONDS, transport.close)

    def connection_lost(self, handler, exc=None):
        timer = self.deadlines.pop(handler, None)
        if timer is not None:
            timer.cancel()
        super().connection_lost(handler, exc)
