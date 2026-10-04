"""Offline lifetime checks through the pinned SDK and real loopback socket I/O."""

import asyncio
from contextlib import asynccontextmanager, suppress
from importlib.metadata import version
import json
from pathlib import Path
import subprocess
import sys
import tomllib
from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr

from app.container import Application
from app.services import gemini_ai_service as gemini


class LocalGeminiServer:
    """Speak enough HTTP for real SDK parsing; stalls end only when sockets close."""

    def __init__(self):
        self.requests = asyncio.Queue()
        self.tasks = set()
        self.mode = "success"

    async def handle(self, reader, writer):
        task = asyncio.current_task()
        self.tasks.add(task)
        request = None
        try:
            head = (await reader.readuntil(b"\r\n\r\n")).decode("ascii")
            lines = head.split("\r\n")
            headers = dict(line.split(": ", 1) for line in lines[1:] if line)
            headers = {key.lower(): value for key, value in headers.items()}
            await reader.readexactly(int(headers.get("content-length", "0")))
            request = SimpleNamespace(
                path=lines[0].split()[1], key=headers["x-goog-api-key"],
                disconnected=asyncio.Event(),
            )
            self.requests.put_nowait(request)
            if self.mode == "stall" or (
                self.mode == "rotation" and request.key == "synthetic-first-key"
            ) or (self.mode == "pages" and "pageToken=" in request.path):
                await reader.read()
            elif self.mode == "trickle":
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 100000\r\n\r\n")
                eof = asyncio.create_task(reader.read())
                try:
                    while not eof.done():
                        writer.write(b" ")
                        await writer.drain()
                        await asyncio.sleep(0.02)
                finally:
                    eof.cancel()
                    await asyncio.gather(eof, return_exceptions=True)
            else:
                status = "200 OK"
                if "gemini-missing:" in request.path:
                    status = "404 Not Found"
                    payload = {"error": {"code": 404, "message": "Missing model"}}
                elif ":generateContent" in request.path:
                    payload = {"candidates": [{"content": {
                        "role": "model", "parts": [{"text": "A friendly response."}],
                    }}]}
                else:
                    payload = {"models": [{
                        "name": "models/gemini-local",
                        "supportedGenerationMethods": ["generateContent"],
                    }]}
                    if self.mode == "pages":
                        payload["nextPageToken"] = "second"
                body = json.dumps(payload).encode()
                writer.write((f"HTTP/1.1 {status}\r\nContent-Type: application/json\r\n"
                              f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n").encode()
                             + body)
                await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()
            with suppress(ConnectionError):
                await writer.wait_closed()
            if request is not None:
                request.disconnected.set()
            self.tasks.discard(task)

    @asynccontextmanager
    async def running(self):
        server = await asyncio.start_server(self.handle, "127.0.0.1", 0)
        self.url = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"
        try:
            yield self
        finally:
            server.close()
            await server.wait_closed()
            for task in list(self.tasks):
                task.cancel()
            await asyncio.gather(*self.tasks, return_exceptions=True)


def wire_real_sdk(monkeypatch, server, backend):
    from google import genai
    from google.genai import _api_client

    # Exercise both native paths, independent of whether TwitchIO brought aiohttp in.
    monkeypatch.setattr(_api_client, "has_aiohttp", backend == "aiohttp")
    for name in ("GOOGLE_API_KEY", "GEMINI_API_KEY", "GOOGLE_GENAI_CLIENT_MODE"):
        monkeypatch.delenv(name, raising=False)
    real_client = genai.Client
    clients = []

    def local_client(**kwargs):
        assert kwargs["api_key"].startswith("synthetic-")
        assert kwargs["vertexai"] is False
        options = kwargs["http_options"]
        assert options.timeout > 0
        assert options.retry_options.attempts == 1
        kwargs["http_options"] = options.model_copy(update={
            "base_url": server.url,
            "client_args": {"trust_env": False},
            "async_client_args": {"trust_env": False},
        })
        client = real_client(**kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(genai, "Client", local_client)

    real_to_thread = asyncio.to_thread

    async def no_network_worker(function, *args, **kwargs):
        # aiohttp reads local proxy configuration in a worker; its socket I/O stays
        # asynchronous. Reject the old SDK's blocking HTTP dispatch specifically.
        assert function.__module__ == "aiohttp.helpers"
        assert function.__name__ == "get_env_proxy_for_url"
        return await real_to_thread(function, *args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", no_network_worker)
    return clients


@pytest.fixture(params=["httpx", "aiohttp"])
async def transport(request, monkeypatch):
    monkeypatch.setattr(gemini, "GEMINI_REQUEST_TIMEOUT_SECONDS", 0.4)
    monkeypatch.setattr(gemini, "GEMINI_DISCOVERY_TIMEOUT_SECONDS", 0.4)
    monkeypatch.setattr(gemini, "GEMINI_TRANSPORT_TIMEOUT_SECONDS", 0.1)
    monkeypatch.setattr(gemini, "GEMINI_DISCOVERY_TRANSPORT_TIMEOUT_SECONDS", 0.1)
    async with LocalGeminiServer().running() as server:
        clients = wire_real_sdk(monkeypatch, server, request.param)
        try:
            yield server, clients
        finally:
            for client in clients:
                await gemini.GeminiAIService._close_client(client)


def new_service():
    return gemini.GeminiAIService(SimpleNamespace(
        gemini_api_key=SecretStr("synthetic-first-key"),
        gemini_model="gemini-local", gemini_fallback_model="gemini-fallback",
    ))


def assert_closed(client):
    # Check the actual transports, not application fakes reporting close calls.
    api = client._api_client
    assert api._httpx_client.is_closed
    assert api._async_httpx_client.is_closed
    if api._aiohttp_session is not None:
        assert api._aiohttp_session.closed


async def run_operation(service, operation):
    if operation == "generation":
        return await service.generate_reply("Hello", "synthetic-viewer")
    return await service.discover_models()


async def assert_failed(task, operation):
    done, _ = await asyncio.wait({task}, timeout=2)
    if not done:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        pytest.fail("Provider missed its own deadline")
    if operation == "generation":
        assert not (await task).is_available
    else:
        with pytest.raises((TimeoutError, httpx.TimeoutException)):
            await task


def test_declared_sdk_is_the_installed_contract():
    project = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    assert "google-genai==1.75.0" in project["project"]["dependencies"]
    assert version("google-genai") == "1.75.0"


async def test_real_sdk_parses_generation_discovery_and_fallback(transport):
    server, clients = transport
    service = new_service()
    assert await service.discover_models() == ["gemini-local"]
    service.settings.gemini_model = "gemini-missing"
    assert (await service.generate_reply("Hello", "synthetic-viewer")).text == "A friendly response."
    service.settings.gemini_model = "gemini-new"
    assert (await service.generate_reply("Hello", "synthetic-viewer")).is_available
    assert len(clients) == 1
    paths = [(await server.requests.get()).path for _ in range(4)]
    assert "gemini-missing:" in paths[1]
    assert "gemini-fallback:" in paths[2]
    assert "gemini-new:" in paths[3]
    await service.aclose()
    assert_closed(clients[0])


@pytest.mark.parametrize("operation", ["generation", "discovery"])
async def test_stalled_socket_has_transport_deadline(transport, monkeypatch, operation):
    server, clients = transport
    server.mode = "stall"
    # The socket timeout must finish before the longer total-operation deadline.
    monkeypatch.setattr(gemini, "GEMINI_REQUEST_TIMEOUT_SECONDS", 5)
    monkeypatch.setattr(gemini, "GEMINI_DISCOVERY_TIMEOUT_SECONDS", 5)
    if operation == "discovery":
        monkeypatch.setattr(gemini, "GEMINI_TRANSPORT_TIMEOUT_SECONDS", 5)
    service = new_service()
    task = asyncio.create_task(run_operation(service, operation))
    request = await asyncio.wait_for(server.requests.get(), 2)
    await assert_failed(task, operation)
    await asyncio.wait_for(request.disconnected.wait(), 1)
    assert server.requests.empty()  # Timeouts do not retry or use a fallback.
    await service.aclose()
    assert_closed(clients[0])


@pytest.mark.parametrize("operation", ["generation", "discovery"])
async def test_total_deadline_cancels_trickling_response(transport, monkeypatch, operation):
    server, _ = transport
    server.mode = "trickle"
    monkeypatch.setattr(gemini, "GEMINI_TRANSPORT_TIMEOUT_SECONDS", 5)
    monkeypatch.setattr(gemini, "GEMINI_DISCOVERY_TRANSPORT_TIMEOUT_SECONDS", 5)
    service = new_service()
    task = asyncio.create_task(run_operation(service, operation))
    request = await asyncio.wait_for(server.requests.get(), 2)
    await assert_failed(task, operation)
    await asyncio.wait_for(request.disconnected.wait(), 1)
    await service.aclose()


async def test_discovery_total_deadline_includes_later_pages(transport, monkeypatch):
    server, _ = transport
    server.mode = "pages"
    monkeypatch.setattr(gemini, "GEMINI_DISCOVERY_TRANSPORT_TIMEOUT_SECONDS", 5)
    service = new_service()
    task = asyncio.create_task(service.discover_models())
    await asyncio.wait_for(server.requests.get(), 2)
    second = await asyncio.wait_for(server.requests.get(), 2)
    assert "pageToken=second" in second.path
    await assert_failed(task, "discovery")
    await asyncio.wait_for(second.disconnected.wait(), 1)
    await service.aclose()


@pytest.mark.parametrize("operation", ["generation", "discovery"])
async def test_cancellation_closes_stalled_socket(transport, monkeypatch, operation):
    server, clients = transport
    server.mode = "stall"
    monkeypatch.setattr(gemini, "GEMINI_TRANSPORT_TIMEOUT_SECONDS", 5)
    monkeypatch.setattr(gemini, "GEMINI_DISCOVERY_TRANSPORT_TIMEOUT_SECONDS", 5)
    service = new_service()
    task = asyncio.create_task(run_operation(service, operation))
    request = await asyncio.wait_for(server.requests.get(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.wait_for(request.disconnected.wait(), 1)
    await service.aclose()
    assert_closed(clients[0])


async def test_rotation_retires_real_old_transport_after_cancel(transport, monkeypatch):
    server, clients = transport
    server.mode = "rotation"
    monkeypatch.setattr(gemini, "GEMINI_TRANSPORT_TIMEOUT_SECONDS", 5)
    monkeypatch.setattr(gemini, "GEMINI_REQUEST_TIMEOUT_SECONDS", 5)
    service = new_service()
    old = asyncio.create_task(run_operation(service, "generation"))
    request = await asyncio.wait_for(server.requests.get(), 2)
    service.settings.gemini_api_key = SecretStr("synthetic-second-key")
    assert (await service.generate_reply("Hello", "synthetic-viewer")).is_available
    second = await asyncio.wait_for(server.requests.get(), 2)
    assert second.key == "synthetic-second-key"
    assert len(clients) == 2
    assert not clients[0]._api_client._async_httpx_client.is_closed
    old.cancel()
    with pytest.raises(asyncio.CancelledError):
        await old
    await asyncio.wait_for(request.disconnected.wait(), 1)
    assert_closed(clients[0])
    assert not clients[1]._api_client._async_httpx_client.is_closed
    await service.aclose()
    assert_closed(clients[1])


@pytest.mark.parametrize("operation", ["generation", "discovery"])
async def test_application_shutdown_drains_stalled_real_provider(transport, operation):
    server, clients = transport
    server.mode = "stall"
    service = new_service()
    closed = []

    class Resource:
        async def aclose(self):
            closed.append("http")

        async def close(self):
            closed.append("database")

    application = Application(
        settings=SimpleNamespace(), database=Resource(), http_client=Resource(),
        ai_service=service, services=SimpleNamespace(), registry=SimpleNamespace(),
        dispatcher=SimpleNamespace(),
    )
    task = asyncio.create_task(run_operation(service, operation))
    request = await asyncio.wait_for(server.requests.get(), 2)
    await asyncio.wait_for(application.shutdown(), 2)
    await assert_failed(task, operation)
    await asyncio.wait_for(request.disconnected.wait(), 1)
    assert_closed(clients[0])
    assert closed == ["http", "database"]
    assert not service.is_available
    await application.shutdown()


async def test_cancelled_shutdown_leaves_lease_responsible_for_cleanup(transport):
    server, clients = transport
    server.mode = "stall"
    service = new_service()
    task = asyncio.create_task(run_operation(service, "generation"))
    request = await asyncio.wait_for(server.requests.get(), 2)
    shutdown = asyncio.create_task(service.aclose())
    await asyncio.sleep(0)
    shutdown.cancel()
    with pytest.raises(asyncio.CancelledError):
        await shutdown
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.wait_for(request.disconnected.wait(), 1)
    assert_closed(clients[0])
    await service.aclose()


@pytest.mark.parametrize("backend", ["httpx", "aiohttp"])
def test_cancelled_provider_does_not_hold_process_exit(backend):
    result = subprocess.run(
        [sys.executable, "-c", "import runpy, sys; runpy.run_path(sys.argv[1], run_name='__main__')",
         str(Path(__file__).resolve()), backend],
        cwd=Path(__file__).parents[1], capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr


async def exit_probe(backend):
    with pytest.MonkeyPatch.context() as monkeypatch:
        async with LocalGeminiServer().running() as server:
            server.mode = "stall"
            clients = wire_real_sdk(monkeypatch, server, backend)
            service = new_service()
            task = asyncio.create_task(service.discover_models())
            request = await asyncio.wait_for(server.requests.get(), 2)
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            await service.aclose()
            await asyncio.wait_for(request.disconnected.wait(), 1)
            assert_closed(clients[0])


if __name__ == "__main__":
    asyncio.run(exit_probe(sys.argv[2]))
