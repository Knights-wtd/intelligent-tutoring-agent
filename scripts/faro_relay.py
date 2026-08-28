"""Raw TCP relay so Docker containers can reach faroapi.com when the WSL2 path
blackholes their TLS handshakes. The host opens the outbound connection (its
path is known-good) and transparently pipes bytes; TLS still originates in the
container, so certificates stay valid.

Usage: python faro_relay.py [listen_port] [remote_host] [remote_port]
Defaults: 17897 faroapi.com 443. Start hidden at login via:
  powershell Start-Process -WindowStyle Hidden python <this file>
"""

import asyncio
import ssl
import time

REMOTE_HOST = "faroapi.com"
REMOTE_PORT = 443


async def pipe(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> None:
    """Copy one direction; on source EOF half-close the destination instead of
    killing the reverse direction mid-flight."""
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except (ConnectionError, TimeoutError, ssl.SSLError, OSError):
        pass
    finally:
        try:
            if writer.can_write_eof():
                writer.write_eof()
        except (ConnectionError, OSError):
            pass


async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        up_reader, up_writer = await asyncio.open_connection(REMOTE_HOST, REMOTE_PORT)
    except OSError:
        try:
            writer.close()
        except OSError:
            pass
        return
    try:
        await asyncio.gather(
            pipe(reader, up_writer),
            pipe(up_reader, writer),
        )
    finally:
        for closer in (writer, up_writer):
            try:
                closer.close()
            except (ConnectionError, OSError):
                pass


async def main(listen_port: int, remote_host: str, remote_port: int) -> None:
    while True:
        try:
            server = await asyncio.start_server(handle, "0.0.0.0", listen_port)
        except OSError as error:
            # Port taken (stale instance) — retry rather than dying silently.
            print(f"relay bind failed ({error}); retrying in 5s", flush=True)
            await asyncio.sleep(5)
            continue
        print(f"relay 0.0.0.0:{listen_port} -> {remote_host}:{remote_port}", flush=True)
        async with server:
            await server.serve_forever()


if __name__ == "__main__":
    import sys
    import traceback

    listen_port = int(sys.argv[1]) if len(sys.argv) > 1 else 17897
    remote_host = sys.argv[2] if len(sys.argv) > 2 else REMOTE_HOST
    remote_port = int(sys.argv[3]) if len(sys.argv) > 3 else REMOTE_PORT
    while True:
        try:
            asyncio.run(main(listen_port, remote_host, remote_port))
        except BaseException:
            traceback.print_exc()
            traceback.print_exc(file=open(f"{__file__}.crash.log", "a", encoding="utf-8"))
            time.sleep(3)
