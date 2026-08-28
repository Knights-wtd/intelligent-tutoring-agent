import asyncio
import importlib.util
from pathlib import Path
from types import ModuleType


def _load_relay() -> ModuleType:
    relay_path = Path(__file__).parents[3] / "scripts" / "faro_relay.py"
    spec = importlib.util.spec_from_file_location("faro_relay", relay_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _close_writer(writer: asyncio.StreamWriter) -> None:
    writer.close()
    try:
        await asyncio.wait_for(writer.wait_closed(), 1)
    except (ConnectionError, TimeoutError):
        pass


def test_connect_proxy_establishes_and_tunnels_only_the_configured_target() -> None:
    relay = _load_relay()

    async def scenario() -> None:
        async def upstream(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            payload = await reader.readexactly(4)
            writer.write(b"pong:" + payload)
            await writer.drain()
            await _close_writer(writer)

        upstream_server = await asyncio.start_server(upstream, "127.0.0.1", 0)
        upstream_port = upstream_server.sockets[0].getsockname()[1]
        proxy_server = None
        try:
            handler = relay.build_connect_handler(
                remote_host="127.0.0.1",
                remote_port=upstream_port,
                allowed_host="faroapi.com",
                allowed_port=443,
            )
            proxy_server = await asyncio.start_server(handler, "127.0.0.1", 0)
            proxy_port = proxy_server.sockets[0].getsockname()[1]
            reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
            writer.write(b"CONNECT faroapi.com:443 HTTP/1.1\r\nHost: faroapi.com:443\r\n\r\n")
            await writer.drain()

            response = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 1)
            assert response.startswith(b"HTTP/1.1 200 Connection Established\r\n")

            writer.write(b"ping")
            await writer.drain()
            assert await asyncio.wait_for(reader.readexactly(9), 1) == b"pong:ping"
            await _close_writer(writer)
        finally:
            if proxy_server is not None:
                proxy_server.close()
                await proxy_server.wait_closed()
            upstream_server.close()
            await upstream_server.wait_closed()

    asyncio.run(scenario())


def test_connect_proxy_rejects_an_unconfigured_target() -> None:
    relay = _load_relay()

    async def scenario() -> None:
        handler = relay.build_connect_handler(
            remote_host="127.0.0.1",
            remote_port=9,
            allowed_host="faroapi.com",
            allowed_port=443,
        )
        proxy_server = await asyncio.start_server(handler, "127.0.0.1", 0)
        proxy_port = proxy_server.sockets[0].getsockname()[1]
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
            writer.write(b"CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\n")
            await writer.drain()

            response = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 1)
            assert response.startswith(b"HTTP/1.1 403 Forbidden\r\n")
            await _close_writer(writer)
        finally:
            proxy_server.close()
            await proxy_server.wait_closed()

    asyncio.run(scenario())
