"""Restricted HTTP CONNECT proxy for Faro calls from Docker containers.

The API configures httpx with ``FARO_PROXY_URL=http://host.docker.internal:17897``.
This process accepts only ``CONNECT faroapi.com:443`` and tunnels that connection
through the host network, where Faro is reachable. It is intentionally not a
general-purpose proxy.

Usage: python faro_relay.py [listen_port] [remote_host] [remote_port]
Defaults: 17897 faroapi.com 443. Start hidden at login via:
  powershell Start-Process -WindowStyle Hidden python <this file>
"""

from __future__ import annotations

import asyncio
import ssl
from collections.abc import Awaitable, Callable
from contextlib import suppress
from functools import partial

REMOTE_HOST = "faroapi.com"
REMOTE_PORT = 443
MAX_CONNECT_HEADER_BYTES = 16 * 1024
CONNECT_HEADER_TIMEOUT_SECONDS = 10


async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Copy one direction and preserve the reverse direction after source EOF."""
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except (ConnectionError, TimeoutError, ssl.SSLError, OSError):
        pass
    finally:
        with suppress(ConnectionError, OSError):
            if writer.can_write_eof():
                writer.write_eof()


async def _respond(writer: asyncio.StreamWriter, status_line: bytes) -> None:
    writer.write(status_line + b"\r\nConnection: close\r\n\r\n")
    with suppress(ConnectionError, OSError):
        await writer.drain()


async def _read_connect_target(
    reader: asyncio.StreamReader,
) -> tuple[str, int] | None:
    try:
        header = await asyncio.wait_for(
            reader.readuntil(b"\r\n\r\n"), CONNECT_HEADER_TIMEOUT_SECONDS
        )
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, TimeoutError):
        return None
    if len(header) > MAX_CONNECT_HEADER_BYTES:
        return None
    try:
        request_line = header.split(b"\r\n", 1)[0].decode("ascii")
        method, authority, version = request_line.split(" ")
        host, port_text = authority.rsplit(":", 1)
        port = int(port_text)
    except (UnicodeDecodeError, ValueError):
        return None
    if method != "CONNECT" or not version.startswith("HTTP/1."):
        return None
    return host.rstrip(".").casefold(), port


async def handle(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    *,
    remote_host: str,
    remote_port: int,
    allowed_host: str,
    allowed_port: int,
) -> None:
    upstream_writer: asyncio.StreamWriter | None = None
    try:
        target = await _read_connect_target(reader)
        if target is None:
            await _respond(writer, b"HTTP/1.1 400 Bad Request")
            return
        if target != (allowed_host.rstrip(".").casefold(), allowed_port):
            await _respond(writer, b"HTTP/1.1 403 Forbidden")
            return
        try:
            upstream_reader, upstream_writer = await asyncio.open_connection(
                remote_host, remote_port
            )
        except OSError:
            await _respond(writer, b"HTTP/1.1 502 Bad Gateway")
            return

        writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await writer.drain()
        await asyncio.gather(
            pipe(reader, upstream_writer),
            pipe(upstream_reader, writer),
        )
    finally:
        writer.close()
        if upstream_writer is not None:
            upstream_writer.close()
        with suppress(ConnectionError, OSError, TimeoutError):
            await asyncio.wait_for(writer.wait_closed(), 1)
        if upstream_writer is not None:
            with suppress(ConnectionError, OSError, TimeoutError):
                await asyncio.wait_for(upstream_writer.wait_closed(), 1)


def build_connect_handler(
    *,
    remote_host: str,
    remote_port: int,
    allowed_host: str,
    allowed_port: int,
) -> Callable[[asyncio.StreamReader, asyncio.StreamWriter], Awaitable[None]]:
    return partial(
        handle,
        remote_host=remote_host,
        remote_port=remote_port,
        allowed_host=allowed_host,
        allowed_port=allowed_port,
    )


async def main(listen_port: int, remote_host: str, remote_port: int) -> None:
    handler = build_connect_handler(
        remote_host=remote_host,
        remote_port=remote_port,
        allowed_host=remote_host,
        allowed_port=remote_port,
    )
    while True:
        try:
            server = await asyncio.start_server(handler, "0.0.0.0", listen_port)
        except OSError as error:
            print(f"relay bind failed ({error}); retrying in 5s", flush=True)
            await asyncio.sleep(5)
            continue
        print(
            f"restricted CONNECT proxy 0.0.0.0:{listen_port} -> {remote_host}:{remote_port}",
            flush=True,
        )
        async with server:
            await server.serve_forever()


if __name__ == "__main__":
    import sys

    listen_port = int(sys.argv[1]) if len(sys.argv) > 1 else 17897
    remote_host = sys.argv[2] if len(sys.argv) > 2 else REMOTE_HOST
    remote_port = int(sys.argv[3]) if len(sys.argv) > 3 else REMOTE_PORT
    try:
        asyncio.run(main(listen_port, remote_host, remote_port))
    except KeyboardInterrupt:
        pass
