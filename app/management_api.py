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
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from aiohttp import web

from app.errors import UserError, error_result
from app.app_settings import AppSettingsStore
from app.bot_runtime import BotRuntime
from app.operation_policy import OperationPolicy
from app.filter_settings import FilterValidationError
from app.management import ApplicationManagement
from app.operations import SERVER, collect, operation, private_context
from app.runtime_paths import PACKAGED_FRONTEND, SOURCE_ROOT, RuntimePaths
from app.utils.logging import RecentLogBuffer
from app.credentials import CredentialError
from app.config.settings import TwitchConfigurationError
from app.twitch_setup import ServerOAuth, TwitchSetup, credential_manager


MAX_BODY = 65536
REQUEST_SECONDS = 25
CONNECTION_SECONDS = 35
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{43,128}\Z")
SESSION_SECONDS = 3600
MAX_SESSIONS = 8
MAX_ASSET = 4 * 1024 * 1024
REQUESTS_PER_MINUTE = 120


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
            raise UserError("management_api.management_must_bind_to_loopback_or_a_trusted_private")
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise UserError("management_api.management_port_must_be_between_1_and_65535")
        if not TOKEN_PATTERN.fullmatch(self.token):
            raise UserError("management_api.management_token_must_be_43_128_url_safe_characters")
        if self.allowed_host is not None:
            # An exact literal authority, never a wildcard, URL, proxy header or DNS suffix.
            match = re.fullmatch(r"(\[[0-9a-fA-F:]+\]|[0-9.]+):([0-9]{1,5})", self.allowed_host)
            if match is None or not 1 <= int(match[2]) <= 65535:
                raise UserError("management_api.management_allowed_host_must_be_an_exact_ip_port")
            ipaddress.ip_address(match[1].strip("[]"))
        if self.trusted_origin is not None:
            # Canonical ASCII DNS origin, with an optional non-default port. No
            # credentials, paths, wildcard/suffix matching or URL normalization.
            origin = self.trusted_origin
            match = re.fullmatch(r"https://([a-z0-9.-]+)(?::([0-9]{1,5}))?", origin)
            if match is None or len(match[1]) > 253 or "." not in match[1]:
                raise UserError("management_api.trusted_origin_must_be_an_exact_lowercase_https_dns")
            if any(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) is None
                   for label in match[1].split(".")) or match[1].replace(".", "").isdigit():
                raise UserError("management_api.trusted_origin_must_contain_a_valid_dns_hostname")
            if match[2] is not None and (not 1 <= int(match[2]) <= 65535
                    or match[2] != str(int(match[2])) or int(match[2]) == 443):
                raise UserError("management_api.trusted_origin_port_must_be_canonical_omit_the_default")
            if self.allowed_host is not None or not self.trusted_proxies:
                raise UserError("management_api.https_proxy_mode_requires_trusted_proxy_ips_and_replaces")
        elif self.trusted_proxies or self.twitch_redirect_uri is not None:
            raise UserError("management_api.trusted_proxies_and_a_remote_callback_require_an_explicit")
        for proxy in self.trusted_proxies:
            peer = ipaddress.ip_address(proxy)
            if peer.is_unspecified or peer.is_multicast or str(peer) != proxy:
                raise UserError("management_api.trusted_proxies_must_be_exact_canonical_ips_never_networks")
        if self.twitch_redirect_uri is not None and self.twitch_redirect_uri != self.trusted_origin + "/oauth/callback":
            raise UserError("management_api.twitch_redirect_must_be_the_trusted_https_origin_followed")
        if address.is_unspecified and self.allowed_host is None and self.trusted_origin is None:
            raise UserError("management_api.an_all_interface_bind_requires_an_explicit_management_allowed")

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
            raise UserError("management_api.set_only_heetkit_management_token_or_heetkit_management_token")
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
            raise UserError("management_api.cannot_read_management_token_file_use_a_private_regular") from None
    if not TOKEN_PATTERN.fullmatch(token):
        raise UserError("management_api.supply_a_private_management_token_generated_from_at_least")
    return token


OPERATIONS_PREFIX = "/v1/ops/"
SERVER_ONLY = {SERVER}


class ServerOperations:
    """Server-host operations and Server-specific views of shared ones."""

    def __init__(self, api: "ManagementAPI") -> None:
        self.api = api

    @property
    def service(self) -> ApplicationManagement:
        return self.api.service

    @operation(write=False, hosts=SERVER_ONLY)
    def get_app_status(self) -> dict:
        return self.api.app_status()

    @operation(write=False, hosts=SERVER_ONLY)
    def get_ai_provider_settings(self, provider: object = None) -> dict:
        result = self.service.get_ai_provider_settings(provider)
        result["settings"]["credential"] = self.api.ai_credential_status(result["settings"]["provider_id"])
        return result

    @operation(write=False, hosts=SERVER_ONLY, passthrough_errors=True)
    def get_ai_setup(self) -> dict:
        result = self.service.get_ai_setup()
        if result.get("ok") is not False:
            for provider in result["providers"]:
                provider["credential"] = self.api.ai_credential_status(provider["id"])
        return result

    @operation(write=True, hosts=SERVER_ONLY)
    async def block_ai_user(self, username: object) -> dict:
        await self.service._block_ai_user(username)
        return self.service.get_blocked_ai_users()

    @operation(write=True, hosts=SERVER_ONLY)
    async def block_ai_user_only(self, username: object) -> None:
        await self.service._block_ai_user(username)

    @operation(write=False, hosts=SERVER_ONLY)
    def get_snapshot(self) -> dict:
        return {"status": self.api.app_status(), "ai_status": self.service.get_ai_status()}

    @operation(write=False, hosts=SERVER_ONLY, passthrough_errors=True)
    def get_management_setup(self, *, owner: bytes) -> dict:
        return self.api.setup_status(owner)

    @operation(write=False, hosts=SERVER_ONLY)
    def get_diagnostics(self) -> dict:
        policy = self.api.policy
        return {"ok": True, "process_uptime_seconds": int(time.monotonic() - self.api.started),
                "desired_running": policy.desired_running, "operation": policy.snapshot(),
                "settings_effect": {"commands_filters_ai_personalities_triggers": "immediate",
                    "twitch_target": "save and reconnect",
                    "twitch_identity_secret": "save, authorize and reconnect",
                    "gemini_key": "immediate",
                    "deepseek_key": "immediate",
                    "privacy_api_bind": "process_restart (configure outside API)"}}

    @operation(write=True, hosts=SERVER_ONLY, passthrough_errors=True)
    async def discover_ai_models(self, provider: object = None) -> dict:
        from app.config.ai_models import validate_ai_provider
        from app.services.ai_provider import AIModelDiscoveryError
        application = self.api.runtime.application
        provider = validate_ai_provider(application.settings.ai_provider if provider is None else provider)
        try:
            models = await application.services.ai.discover_models(provider)
        except AIModelDiscoveryError as error:
            return {**error_result(error), "provider_id": provider}
        return {"ok": True, "models": models, "provider_id": provider}

    @operation(write=True, hosts=SERVER_ONLY)
    def start_bot(self) -> dict:
        self.api.setup.require_ready()
        return {"ok": True, "changed": self.api.policy.connect(), "operation": self.api.policy.snapshot()}

    @operation(write=True, hosts=SERVER_ONLY)
    def stop_bot(self) -> dict:
        return {"ok": True, "changed": self.api.policy.disconnect(), "operation": self.api.policy.snapshot()}

    @operation(write=True, hosts=SERVER_ONLY)
    def set_bot_mode(self, mode: object) -> dict:
        return {"ok": True, "changed": self.api.policy.set_mode(mode), "operation": self.api.policy.snapshot()}

    async def _change_filters(self, payload: object, *, save: bool) -> dict:
        try:
            await self.service._change_filters(payload, save=save)
        except FilterValidationError as error:
            return {"ok": False,
                    "error_code": "management_api.invalid_regex_rule" if error.category == "patterns" else "management_api.invalid_filter_rule_text", "error_params": {},
                    "invalid_rule": {"category": error.category, "index": error.index}}
        return {"ok": True}

    @operation(write=True, hosts=SERVER_ONLY, passthrough_errors=True)
    async def save_filters(self, payload: object) -> dict:
        return await self._change_filters(payload, save=True)

    @operation(write=True, hosts=SERVER_ONLY, passthrough_errors=True)
    async def apply_filters(self, payload: object) -> dict:
        return await self._change_filters(payload, save=False)

    @operation(write=True, hosts=SERVER_ONLY, passthrough_errors=True)
    async def test_filters(self, text: object, source: object, payload: object) -> dict:
        return await self.service._test_filters(text, source, payload)

    @operation(write=False, hosts=SERVER_ONLY)
    def get_recent_commands(self) -> dict:
        buffer = self.api.log_buffer
        return {"ok": True, "entries": buffer.recent_commands() if buffer else []}

    @operation(write=True, hosts=SERVER_ONLY)
    def get_recent_logs(self, after_id: object = 0, limit: object = 100, snapshot: object = False) -> dict:
        if (type(after_id) is not int or after_id < 0 or type(limit) is not int or not 1 <= limit <= 200
                or type(snapshot) is not bool or (snapshot and after_id != 0)):
            raise ValueError
        buffer = self.api.log_buffer
        return {"ok": True, **(buffer.activity(after_id=after_id, limit=limit, snapshot=snapshot)
                               if buffer else {"entries": [], "next_after_id": after_id})}

    @operation(write=True, hosts=SERVER_ONLY, passthrough_errors=True)
    async def start_ai_playground(self, prompt: object, *, owner: bytes) -> dict:
        return await self.service._start_ai_playground(prompt, owner=owner, expires_at=self.api.sessions.get(owner))

    @operation(write=True, hosts=SERVER_ONLY, passthrough_errors=True)
    async def get_ai_playground_result(self, request_id: object, *, owner: bytes) -> dict:
        return await self.service._get_ai_playground_result(request_id, owner=owner)

    @operation(write=True, hosts=SERVER_ONLY, passthrough_errors=True)
    async def cancel_ai_playground(self, request_id: object, *, owner: bytes) -> dict:
        return await self.service._cancel_ai_playground(request_id, owner=owner)

    @operation(write=True, hosts=SERVER_ONLY, passthrough_errors=True)
    async def update_server_twitch_settings(self, client_id, bot_username, bot_user_id, channel, channel_user_id):
        return await self.api.setup.save_twitch(client_id=client_id, bot_username=bot_username,
            bot_user_id=bot_user_id, channel=channel, channel_user_id=channel_user_id)

    @operation(write=True, hosts=SERVER_ONLY, passthrough_errors=True)
    def save_twitch_preset(self, preset_id, display_name, channel, channel_user_id):
        return self.api.setup.save_preset(preset_id=preset_id, display_name=display_name,
                                          channel=channel, channel_user_id=channel_user_id)

    @operation(write=True, hosts=SERVER_ONLY, passthrough_errors=True)
    def delete_twitch_preset(self, preset_id):
        return self.api.setup.delete_preset(preset_id=preset_id)

    @operation(write=True, hosts=SERVER_ONLY, passthrough_errors=True)
    async def switch_server_twitch_preset(self, preset_id):
        return await self.api.setup.switch_preset(preset_id=preset_id)

    @operation(write=True, hosts=SERVER_ONLY, passthrough_errors=True)
    async def replace_credential(self, name, value):
        # Fixed fields: no caller may smuggle the internal remove flag.
        return await self.api.setup.change_credential(name, value)

    @operation(write=True, hosts=SERVER_ONLY, passthrough_errors=True)
    async def remove_credential(self, name):
        return await self.api.setup.change_credential(name, remove=True)

    @operation(write=True, hosts=SERVER_ONLY, passthrough_errors=True)
    async def test_credential(self, name):
        return await self.api.setup.test_credential(name)

    @operation(write=True, hosts=SERVER_ONLY, passthrough_errors=True)
    async def begin_twitch_authorization(self, *, owner: bytes):
        return await self.api.setup.begin(owner)

    @operation(write=True, hosts=SERVER_ONLY, passthrough_errors=True)
    async def complete_twitch_authorization(self, callback_url, *, owner: bytes):
        return await self.api.setup.complete(owner, callback_url)

    @operation(write=True, hosts=SERVER_ONLY, passthrough_errors=True)
    def cancel_twitch_authorization(self, *, owner: bytes):
        return self.api.setup.cancel(owner)


SHARED_OPERATIONS = {name: op for name, op in collect(ApplicationManagement).items()}
SERVER_OPERATIONS = collect(ServerOperations)
OPERATIONS = {**{name: op for name, op in SHARED_OPERATIONS.items() if SERVER in op.hosts}, **SERVER_OPERATIONS}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise UserError("management_api.duplicate_json_key")
        result[key] = value
    return result


def _invalid_constant(_value):
    raise UserError("management_api.non_finite_json_number")


class ManagementAPI:
    def __init__(self, runtime: BotRuntime, config: ManagementConfig,
                 log_buffer: RecentLogBuffer | None = None, *, policy: OperationPolicy | None = None,
                 app_settings: AppSettingsStore | None = None, credentials=None) -> None:
        self.runtime = runtime
        self.config = config
        store = app_settings or AppSettingsStore(RuntimePaths.default().app_settings)
        self.service = ApplicationManagement(runtime.application, store, log_buffer)
        self.policy = policy or OperationPolicy(runtime, store)
        self.setup = TwitchSetup(runtime, self.policy, store,
            credentials or credential_manager(runtime.application.settings),
            oauth=ServerOAuth(redirect_uri=config.oauth_redirect_uri,
                owner_active=self.owner_active))
        self.operations = ServerOperations(self)
        self._owns_policy = policy is None
        self.lock = asyncio.Lock()
        self.runner: web.ServerRunner | None = None
        self.site: web.TCPSite | None = None
        self.active = 0
        self.requests: deque[float] = deque()
        self.public_requests: deque[float] = deque()
        self.asset_requests: deque[float] = deque()
        self.callback_active = False
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
            await self.runtime.application.ai_playground.close()
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

    @staticmethod
    def _admit_request(requests: deque[float], now: float) -> bool:
        while requests and now - requests[0] >= 60:
            requests.popleft()
        if len(requests) >= REQUESTS_PER_MINUTE:
            return False
        requests.append(now)
        return True

    async def oauth_callback(self, request: web.BaseRequest, now: float) -> web.Response:
        # Never render or reflect query parameters. A fixed clean redirect drops
        # codes/state from the final address and referrer; proxies must omit logs.
        if (request.method != "GET" or request.content_length not in (None, 0)
                or "Transfer-Encoding" in request.headers or "Content-Encoding" in request.headers
                or request.raw_path.split("?", 1)[0] != "/oauth/callback"):
            if not self._admit_request(self.public_requests, now):
                return self.response(429, {"ok": False, "error_code": "management_api.management_request_limit_reached", "error_params": {}})
            return self.response(400, {"ok": False, "error_code": "management_api.invalid_oauth_callback", "error_params": {}})
        attempt = self.setup.pending_callback(request.rel_url.raw_query_string)
        if attempt is None or self.callback_active:
            if not self._admit_request(self.public_requests, now):
                return self.response(429, {"ok": False, "error_code": "management_api.management_request_limit_reached", "error_params": {}})
        else:
            self.callback_active = True
            try:
                async with asyncio.timeout(REQUEST_SECONDS):
                    async with self.lock:
                        await self.setup.complete_callback(*attempt)
            except Exception:
                # Details are visible only as fixed status in the initiating tab.
                # A cancelled/timed-out exchange must never be retried automatically.
                pass
            finally:
                self.callback_active = False
        response = self.response(303, {"ok": True})
        response.headers["Location"] = "/oauth/result"
        return response

    @staticmethod
    def response(status: int, payload: dict) -> web.Response:
        encoded = json.dumps(payload, ensure_ascii=True, allow_nan=False)
        if len(encoded) > 2 * 1024 * 1024:
            status, encoded = 500, json.dumps(error_result("management_api.response_exceeds_limit"))
        response = web.Response(status=status, text=encoded, content_type="application/json",
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                     "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
                     "Referrer-Policy": "no-referrer"})
        response.force_close()
        return response

    def asset(self, path: str, now: float) -> web.Response:
        """Serve only Vite's public entry/icon and compiled JS/CSS, never profiles."""
        if path in ("/", "/index.html"):
            relative, content_type = "index.html", "text/html"
        elif path == "/icon.png":
            relative, content_type = "icon.png", "image/png"
        elif re.fullmatch(r"/assets/[A-Za-z0-9_-]+\.(js|css)", path):
            relative = path[1:]
            content_type = "text/javascript" if path.endswith(".js") else "text/css"
        else:
            if not self._admit_request(self.public_requests, now):
                return self.response(429, {"ok": False, "error_code": "management_api.management_request_limit_reached", "error_params": {}})
            return self.response(404, {"ok": False, "error_code": "management_api.unknown_management_resource", "error_params": {}})
        if not self._admit_request(self.asset_requests, now):
            return self.response(429, {"ok": False, "error_code": "management_api.management_request_limit_reached", "error_params": {}})
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
            return self.response(503, {"ok": False, "error_code": "management_api.browser_panel_assets_unavailable_build_the_frontend_before_starting", "error_params": {}})
        response = web.Response(body=body, content_type=content_type, headers={
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self'; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
            "Referrer-Policy": "no-referrer", "Cross-Origin-Resource-Policy": "same-origin",
            "X-Frame-Options": "DENY",
        })
        response.force_close()
        return response

    async def handle(self, request: web.BaseRequest) -> web.Response:
        def reject(status, code):
            return self.response(status, error_result(code))

        def reject_public(status, message):
            if not self._admit_request(self.public_requests, now):
                return reject(429, "management_api.management_request_limit_reached")
            return reject(status, message)

        now = time.monotonic()
        oauth_navigation = (self.config.oauth_callback_enabled
            and request.path in ("/oauth/callback", "/oauth/result")
            and request.headers.get("Host") == urlsplit(self.config.oauth_redirect_uri).netloc)
        if (len(request.headers.getall("Host", [])) != 1 or
                (request.headers.get("Host") not in self.config.authorities and not oauth_navigation)):
            return reject_public(403, "management_api.untrusted_host")
        if not self.config.accepts_proxy(request):
            return reject_public(403, "management_api.untrusted_proxy_headers_or_peer_check_the_configured_https")
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
            return reject_public(403, "management_api.untrusted_browser_origin")
        if callback:
            return await self.oauth_callback(request, now)
        if request.query_string or request.raw_path != request.path:
            return reject_public(400, "management_api.use_an_exact_path_without_query_parameters")
        if request.method not in ("GET", "POST"):
            return reject_public(405, "management_api.method_not_supported")
        if not request.path.startswith("/v1/"):
            if request.method != "GET" or request.content_length not in (None, 0):
                return reject_public(405, "management_api.assets_require_get_without_a_body")
            if request.path == "/oauth/result" and oauth_navigation:
                if not self._admit_request(self.asset_requests, now):
                    return reject(429, "management_api.management_request_limit_reached")
                response = self.response(200, {})
                response.text = "Twitch authorization attempt finished. Close this tab and return to the signed-in Settings tab for the result. If it is still waiting, check callback reachability, registered redirect and proxy settings, then try again."
                response.content_type = "text/plain"
                return response
            return self.asset(request.path, now)
        authorization = request.headers.getall("Authorization", [])
        expected = "Bearer " + self.config.token
        self.sessions = {key: expiry for key, expiry in self.sessions.items() if expiry > now}
        supplied = authorization[0] if len(authorization) == 1 else ""
        admin = hmac.compare_digest(supplied.encode("utf-8"), expected.encode("ascii"))
        digest = hashlib.sha256(supplied.removeprefix("Bearer ").encode("utf-8")).digest()
        session = supplied.startswith("Bearer ") and digest in self.sessions
        if not (admin or session):
            return reject_public(401, "management_api.authentication_required")
        if request.path == "/v1/session" and (admin != (request.method == "POST")):
            return reject(401, "management_api.authentication_required")
        if self.active >= 16 or not self._admit_request(self.requests, now):
            return reject(429, "management_api.management_request_limit_reached")
        if "Content-Encoding" in request.headers or "Transfer-Encoding" in request.headers:
            return reject(400, "management_api.encoded_or_streamed_bodies_are_not_supported")
        self.active += 1
        try:
            async with asyncio.timeout(REQUEST_SECONDS):
                payload = {}
                if request.method == "POST":
                    if request.content_type != "application/json":
                        return reject(415, "management_api.use_application_json")
                    length = request.content_length
                    operation = self.operation_for(request.method, request.path)
                    maximum = operation.max_body if operation is not None else MAX_BODY
                    if length is None or length < 2 or length > maximum:
                        return reject(413, "management_api.json_body_exceeds_this_operation_s_size_limit")
                    async with asyncio.timeout(5):
                        raw = await request.content.readexactly(length)
                    payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                                         parse_constant=_invalid_constant)
                    if not isinstance(payload, dict):
                        return reject(400, "management_api.json_body_must_be_an_object")
                elif request.content_length not in (None, 0):
                    return reject(400, "management_api.get_does_not_accept_a_body")
                # The lock spans awaited lifecycle/block operations as well as
                # synchronous store transactions. All mutations run on the core loop.
                async with self.lock:
                    # A queued request must not outlive logout/session expiry.
                    if session and self.sessions.get(digest, 0) <= time.monotonic():
                        return reject(401, "management_api.session_expired_sign_again")
                    if request.path == "/v1/session":
                        if payload:
                            raise ValueError
                        result = {"ok": True}
                        if request.method == "POST":
                            token = secrets.token_urlsafe(32)
                            if len(self.sessions) >= MAX_SESSIONS:
                                evicted = next(iter(self.sessions))
                                self.setup.cancel(evicted)
                                self.runtime.application.ai_playground.revoke(evicted)
                                del self.sessions[evicted]
                            self.sessions[hashlib.sha256(token.encode("ascii")).digest()] = now + SESSION_SECONDS
                            result.update(token=token, expires_in=SESSION_SECONDS)
                    elif request.method == "POST" and request.path == "/v1/session/logout":
                        if payload:
                            raise ValueError
                        self.sessions.pop(digest, None)
                        self.setup.cancel(digest)
                        self.runtime.application.ai_playground.revoke(digest)
                        result = {"ok": True}
                    else:
                        result = await self.dispatch(request.method, request.path, payload, owner=digest)
                status = 200 if result.get("ok", True) else 400
                return self.response(status, result)
        except TimeoutError:
            return reject(504, "management_api.management_operation_timed_out_inspect_current")
        except LookupError:
            return reject(404, "management_api.unknown_management_resource")
        except (CredentialError, TwitchConfigurationError) as error:
            return self.response(400, error_result(error))
        except (ValueError, TypeError, RecursionError, UnicodeError, asyncio.IncompleteReadError):
            return reject(400, "management_api.invalid_management_input")
        except Exception:
            # Domain errors may contain provider secrets or paths; never serialize
            # exception strings/tracebacks, even for authenticated administrators.
            return reject(500, "management_api.management_operation_failed_check_private_profile")
        finally:
            self.active -= 1

    @staticmethod
    def operation_for(method: str, path: str):
        """The operation a request addresses, or None for session paths; LookupError if unknown."""
        if path.startswith(OPERATIONS_PREFIX):
            operation = OPERATIONS.get(path.removeprefix(OPERATIONS_PREFIX)) if method == "POST" else None
        elif path in ("/v1/session", "/v1/session/logout"):
            return None
        else:
            operation = None
        if operation is None:
            raise LookupError
        return operation

    async def dispatch(self, method: str, path: str, payload: dict, *, owner: bytes = b"") -> dict:
        return await self.call(self.operation_for(method, path), payload, owner=owner)

    async def call(self, operation, payload: dict, *, owner: bytes = b"") -> dict:
        server_owned = operation.name in SERVER_OPERATIONS
        try:
            arguments = operation.bind(payload)
            method = getattr(self.operations if server_owned else self.service, operation.attribute)
            result = method(**arguments, **private_context(method, owner=owner))
            if inspect.isawaitable(result):
                result = await result
        except UserError as error:
            result = error_result(error)
        if not isinstance(result, dict):
            result = {"ok": True}
        # Domain validators remain authoritative; never echo their exception
        # text (some legacy validators interpolate supplied values).
        if result.get("ok") is False:
            if operation.passthrough_errors or result.get("code") == "command_name_conflict":
                return result
            return {"ok": False, "error_code": "management_api.operation_rejected_check_input_profile_storage", "error_params": {}}
        if operation.write and not server_owned:
            self.policy.refresh_command_monitoring()
        return result

    def credential_statuses(self) -> list[dict]:
        """Presence/source only; never read values back to the browser."""
        return self.setup.credentials.server_statuses()

    def ai_credential_status(self, provider: str) -> dict:
        return next(status for status in self.credential_statuses() if status["name"] == provider + "_api_key")

    def setup_status(self, owner: bytes = b"") -> dict:
        """Project effective configuration status, never credentials or paths."""
        credentials = self.credential_statuses()
        provider = self.service.get_ai_provider_settings()["settings"]
        provider["credential"] = self.ai_credential_status(provider["provider_id"])
        state = self.service.get_app_status()
        return self.setup.server_status(state, credentials, provider, owner,
            management_url=self.config.trusted_origin or "http://" + sorted(self.config.authorities)[0],
            authorization_mode="redirect" if self.config.oauth_callback_enabled else "paste")


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
