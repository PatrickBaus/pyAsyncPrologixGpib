"""Tests for the IP connection classes."""

import asyncio
import time

import pytest

from prologix_gpib_async.ip_connection import AsyncSharedIPConnection, _AsyncIPConnection

from .fake_prologix import FakePrologix, run


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


def test_shared_connection_uses_own_timeout():
    """Two clients sharing a pooled connection each keep their own read timeout."""

    async def main():
        async with FakePrologix() as adapter:  # never replies
            async with (
                AsyncSharedIPConnection("127.0.0.1", adapter.port, timeout=10) as slow,
                AsyncSharedIPConnection("127.0.0.1", adapter.port, timeout=0.2) as fast,
            ):
                assert adapter.connections == 1  # the connection really is shared
                start = time.monotonic()
                with pytest.raises(asyncio.TimeoutError):
                    await fast.read(eol_character=b"\n")
                elapsed = time.monotonic() - start
                await slow.write(b"keep slow in use")
                return elapsed

    assert run(main(), timeout=3) < 1
