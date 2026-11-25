"""Where the custom AI endpoint may connect, checked on save and on every connection.

Desktop ("local"): HTTPS anywhere, HTTP only to this computer (as before).
Server ("public"): only public addresses over HTTPS. Server ("private", set with
HEETKIT_CUSTOM_AI_PRIVATE_NETWORKS=true): also loopback, LAN and Tailscale-style
private addresses over HTTP or HTTPS. Link-local (cloud metadata), multicast,
unspecified and reserved addresses are always refused. Server resolves the name on
each connection and connects only to the checked address, so DNS cannot swap in
another one between the check and the connect.
"""

from __future__ import annotations

import asyncio
import socket
import ssl
from ipaddress import IPv4Address, IPv6Address, ip_address
from typing import Iterable
from urllib.parse import urlsplit

import certifi
import httpcore
import httpx

from app.config.ai_models import is_loopback_host, validate_custom_base_url
from app.errors import UserError

NETWORK_POLICIES = ("local", "public", "private")
PRIVATE_NETWORKS_ENV = "HEETKIT_CUSTOM_AI_PRIVATE_NETWORKS"


class CustomAddressRefused(RuntimeError):
    """The endpoint resolved to an address this host's policy does not allow."""


def address_allowed(address: IPv4Address | IPv6Address, *, https: bool, private_networks: bool) -> bool:
    if isinstance(address, IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    if address.is_loopback:  # IPv6 ::1 also counts as reserved.
        return private_networks
    if address.is_link_local or address.is_multicast or address.is_unspecified or address.is_reserved:
        return False
    if address.is_global:
        return https
    return private_networks


def validate_custom_url_for_host(value: object, policy: str) -> str:
    """Save-time check; names are resolved later, on every connection."""
    if policy == "local":
        return validate_custom_base_url(value)
    url = validate_custom_base_url(value, local_http_only=False)
    parts = urlsplit(url)
    private_networks = policy == "private"
    if parts.scheme.lower() == "http" and not private_networks:
        raise UserError("ai_models.custom_base_url_server_public_https")
    host = (parts.hostname or "").removesuffix(".")
    try:
        literal = ip_address(host)
    except ValueError:
        if is_loopback_host(host) and not private_networks:
            raise UserError("ai_models.custom_base_url_server_public_https") from None
        return url
    if not address_allowed(literal, https=True, private_networks=True):
        raise UserError("ai_models.custom_base_url_address_blocked")
    if not address_allowed(literal, https=parts.scheme.lower() == "https", private_networks=private_networks):
        raise UserError("ai_models.custom_base_url_server_public_https")
    return url


class _CheckedBackend(httpcore.AsyncNetworkBackend):
    """Resolve once, refuse any disallowed answer, then connect to a checked address."""

    def __init__(self, *, https: bool, private_networks: bool) -> None:
        self._backend = httpcore.AnyIOBackend()
        self._https = https
        self._private_networks = private_networks

    async def connect_tcp(self, host: str, port: int, timeout: float | None = None,
                          local_address: str | None = None,
                          socket_options: Iterable | None = None) -> httpcore.AsyncNetworkStream:
        async with asyncio.timeout(timeout):
            answers = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
        addresses = list(dict.fromkeys(ip_address(answer[4][0]) for answer in answers))
        if not addresses or not all(address_allowed(address, https=self._https,
                                                    private_networks=self._private_networks)
                                    for address in addresses):
            raise CustomAddressRefused("The custom AI address is not allowed on this host.")
        error: Exception | None = None
        for address in addresses:
            try:
                return await self._backend.connect_tcp(str(address), port, timeout=timeout,
                    local_address=local_address, socket_options=socket_options)
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as failure:
                error = failure
        raise error  # type: ignore[misc]

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


class _CheckedTransport(httpx.AsyncHTTPTransport):
    def __init__(self, *, https: bool, private_networks: bool) -> None:
        super().__init__(trust_env=False)
        # httpx exposes no network-backend option; swap only its connection pool.
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl.create_default_context(cafile=certifi.where()),
            network_backend=_CheckedBackend(https=https, private_networks=private_networks))


def custom_transport(policy: str, base_url: str) -> httpx.AsyncBaseTransport | None:
    """None keeps the default transport (Desktop); raises when the address is refused."""
    parts = urlsplit(base_url)
    https = parts.scheme.lower() == "https"
    if policy == "local":
        # A hand-edited profile cannot widen Desktop's rule.
        if not https and not is_loopback_host(parts.hostname or ""):
            raise CustomAddressRefused("The custom AI address is not allowed on this host.")
        return None
    return _CheckedTransport(https=https, private_networks=policy == "private")
