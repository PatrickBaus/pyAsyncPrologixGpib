"""Tests for the IP connection classes."""

import asyncio

from prologix_gpib_async.ip_connection import _AsyncIPConnection

from .fake_prologix import run


async def _serve_once(payload: bytes):
    """Start a server that sends payload, then closes the connection."""

    async def handle(_reader, writer):
        writer.write(payload)
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1]


def test_partial_read_returns_partial_data():
    """If the host closes the connection mid-message, the partial data is returned."""

    async def main():
        server, port = await _serve_once(b"abc")
        async with server:
            conn = _AsyncIPConnection("127.0.0.1", port)
            await conn.connect()
            try:
                return await conn.read(eol_character=b"\n")
            finally:
                await conn.disconnect()

    assert run(main()) == b"abc"
