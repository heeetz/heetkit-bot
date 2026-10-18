"""Opt-in private, single-administrator HTTP transport for the shared core."""

from __future__ import annotations

import asyncio
import hmac
import inspect
import ipaddress
import json
import logging
import os
import re
import stat
import time
from collections import deque
from dataclasses import asdict, dataclass, field

from aiohttp import web

from app.app_settings import AppSettingsStore
from app.bot_runtime import BotRuntime
from app.management import ApplicationManagement
from app.runtime_paths import RuntimePaths
from app.utils.logging import RecentLogBuffer


MAX_BODY = 65536
REQUEST_SECONDS = 25
CONNECTION_SECONDS = 35
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{43,128}\Z")


@dataclass(frozen=True)
class ManagementConfig:
    token: str = field(repr=False)
    host: str = "127.0.0.1"
    port: int = 8765
    allowed_host: str | None = None

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
        if address.is_unspecified and self.allowed_host is None:
            raise ValueError("An all-interface bind requires an explicit management allowed host.")

    @property
    def authorities(self) -> set[str]:
        if self.allowed_host:
            return {self.allowed_host}
        authority = f"[{self.host}]:{self.port}" if ":" in self.host else f"{self.host}:{self.port}"
        return {authority, f"localhost:{self.port}"} if ipaddress.ip_address(self.host).is_loopback else {authority}


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
    "/v1/commands/save": "save_command_settings",
    "/v1/commands/reset": "reset_command_settings",
    "/v1/commands/remove": "remove_builtin_command",
    "/v1/commands/restore": "restore_builtin_command",
    "/v1/commands/responses/save": "save_command_responses",
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
    "/v1/personalities/reset": "reset_personality",
    "/v1/ai/instructions/save": "save_profile_instructions",
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
                 log_buffer: RecentLogBuffer | None = None) -> None:
        self.runtime = runtime
        self.config = config
        self.service = ApplicationManagement(runtime.application,
            AppSettingsStore(RuntimePaths.default().app_settings), log_buffer)
        self.lock = asyncio.Lock()
        self.runner: web.ServerRunner | None = None
        self.site: web.TCPSite | None = None
        self.active = 0
        self.requests: deque[float] = deque()
        self.started = time.monotonic()
        self.desired_running = True
        self.generation = 0
        self.log_buffer = log_buffer

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
        except BaseException:
            await self.close()
            raise

    async def close(self) -> None:
        if self.runner is not None:
            await self.runner.cleanup()
            self.runner = None

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

    async def handle(self, request: web.BaseRequest) -> web.Response:
        def reject(status, message):
            return self.response(status, {"ok": False, "error": message})
        now = time.monotonic()
        while self.requests and now - self.requests[0] >= 60:
            self.requests.popleft()
        if len(self.requests) >= 120 or self.active >= 16:
            return reject(429, "Management request limit reached.")
        self.requests.append(now)
        if (len(request.headers.getall("Host", [])) != 1 or
                request.headers.get("Host") not in self.config.authorities):
            return reject(403, "Untrusted Host.")
        if ("Origin" in request.headers or "Cookie" in request.headers or
                request.headers.get("Sec-Fetch-Site", "none") != "none"):
            return reject(403, "Browser-origin requests are not supported.")
        authorization = request.headers.getall("Authorization", [])
        expected = "Bearer " + self.config.token
        if len(authorization) != 1 or not hmac.compare_digest(authorization[0].encode("utf-8"), expected.encode("ascii")):
            return reject(401, "Authentication required.")
        if request.query_string or request.raw_path != request.path:
            return reject(400, "Use an exact API path without query parameters.")
        if "Content-Encoding" in request.headers or "Transfer-Encoding" in request.headers:
            return reject(400, "Encoded or streamed bodies are not supported.")
        if request.method not in ("GET", "POST"):
            return reject(405, "Method not supported.")
        self.active += 1
        try:
            async with asyncio.timeout(REQUEST_SECONDS):
                payload = {}
                if request.method == "POST":
                    if request.content_type != "application/json":
                        return reject(415, "Use application/json.")
                    length = request.content_length
                    if length is None or length < 2 or length > MAX_BODY:
                        return reject(413, "JSON body must be 2-65536 bytes.")
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
                    result = await self.dispatch(request.method, request.path, payload)
                status = 200 if result.get("ok", True) else 400
                return self.response(status, result)
        except TimeoutError:
            return reject(504, "Management operation timed out; inspect current state before retrying.")
        except LookupError:
            return reject(404, "Unknown management resource.")
        except (ValueError, TypeError, RecursionError, UnicodeError, asyncio.IncompleteReadError):
            return reject(400, "Invalid management input.")
        except Exception:
            # Domain errors may contain provider secrets or paths; never serialize
            # exception strings/tracebacks, even for authenticated administrators.
            return reject(500, "Management operation failed; check private profile storage and connection state.")
        finally:
            self.active -= 1

    async def dispatch(self, method: str, path: str, payload: dict) -> dict:
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
            return result
        if method == "GET" and path == "/v1/diagnostics":
            return {"ok": True, "process_uptime_seconds": int(time.monotonic() - self.started),
                    "desired_running": self.desired_running,
                    "settings_effect": {"commands_filters_ai_personalities_triggers": "immediate",
                        "twitch_target": "reconnect (configure while stopped outside API)",
                        "identity_credentials_privacy_api_bind": "process_restart (configure outside API)"}}
        if method == "POST" and path in ("/v1/bot/start", "/v1/bot/stop"):
            if payload:
                raise ValueError
            start = path.endswith("/start")
            if not start:
                # Publish intent before the session observer can see completion.
                self.desired_running = False
            changed = await (self.runtime.start_bot() if start else self.runtime.stop_bot())
            self.desired_running = start
            self.generation += int(changed)
            return {"ok": True, "changed": changed}
        if method == "POST" and path in ("/v1/filters/save", "/v1/filters/test"):
            if path.endswith("/save"):
                if set(payload) != {"payload"}:
                    raise ValueError
                await self.service._change_filters(payload["payload"], save=True)
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
            # Only lifecycle codes and safe fixed messages; raw logger text/context
            # can contain chat/provider payloads and is deliberately not returned.
            entries = self.log_buffer.recent(after_id=after, limit=limit) if self.log_buffer else []
            return {"ok": True, "entries": [{"id": entry["id"], "timestamp": entry["timestamp"],
                "level": entry["level"], "message": "Twitch lifecycle: " + entry["event_kind"]}
                for entry in entries if entry.get("event_kind") in {
                    "twitch.subscribe", "twitch.connected", "twitch.recovered", "twitch.disconnected",
                    "twitch.auth_required", "twitch.failed", "twitch.shutdown"}]}
        raise LookupError


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
