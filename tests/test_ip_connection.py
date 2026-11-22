"""Tests for the IP connection classes."""

import asyncio
import errno
import os
import socket
import time
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest

from prologix_gpib_async.ip_connection import (
    DEFAULT_WAIT_TIMEOUT,
    AsyncSharedIPConnection,
    ConnectionLostError,
    NetworkError,
    NotConnectedError,
    _AsyncIPConnection,
    _AsyncIPConnectionPool,
    _AsyncPooledIPConnection,
)

from .fake_prologix import FakePrologix, run


async def _serve_once(payload: bytes) -> tuple[asyncio.Server, int]:
    """Start a server that sends payload, then closes the connection."""

    async def handle(_reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.write(payload)
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port: int = server.sockets[0].getsockname()[1]
    return server, port


def test_partial_read_returns_partial_data() -> None:
    """If the host closes the connection mid-message, the partial data is returned."""

    async def main() -> bytes:
        server, port = await _serve_once(b"abc")
        async with server:
            conn = _AsyncIPConnection("127.0.0.1", port)
            await conn.connect()
            try:
                return await conn.read(eol_character=b"\n")
            finally:
                await conn.disconnect()

    assert run(main()) == b"abc"


def test_shared_connection_uses_own_timeout() -> None:
    """Two clients sharing a pooled connection each keep their own read timeout."""

    async def main() -> float:
        async with FakePrologix() as adapter:  # never replies
            async with (
                AsyncSharedIPConnection("127.0.0.1", adapter.port, timeout=10) as slow,
                AsyncSharedIPConnection("127.0.0.1", adapter.port, timeout=0.2) as fast,
            ):
                assert adapter.connections == 1  # the connection really is shared
                start = time.monotonic()
                with pytest.raises(TimeoutError):
                    await fast.read(eol_character=b"\n")
                elapsed = time.monotonic() - start
                await slow.write(b"keep slow in use")
                return elapsed

    assert run(main(), timeout=3) < 1


def _closed_port() -> int:
    """Returns a port on localhost, that nobody listens to."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
        return port


def _writer(conn: _AsyncIPConnection) -> asyncio.StreamWriter:
    writer: asyncio.StreamWriter = conn._AsyncIPConnection__writer  # type: ignore[attr-defined]  # pylint: disable=W0212
    return writer


def test_connection_properties() -> None:
    """The properties reflect the constructor arguments, the timeout falls back to the default."""
    conn = _AsyncIPConnection("127.0.0.1", 4321)
    assert (conn.hostname, conn.port, conn.timeout) == ("127.0.0.1", 4321, DEFAULT_WAIT_TIMEOUT)
    assert str(conn) == "AsyncIPConnection(127.0.0.1:4321)"
    assert not conn.is_connected


def test_connection_context_manager() -> None:
    """The context manager connects and disconnects."""

    async def main() -> tuple[bytes, int]:
        async with FakePrologix({b"ping": b"pong\n"}) as adapter:
            async with _AsyncIPConnection("127.0.0.1", adapter.port) as conn:
                assert conn.is_connected
                await conn.connect()  # Connecting again does nothing
                await conn.write(b"ping\n")
                data = await conn.read(eol_character=b"\n")
            assert not conn.is_connected
            await conn.disconnect()  # Disconnecting again does nothing
            return data, adapter.connections

    assert run(main()) == (b"pong\n", 1)


def test_connect_to_other_host() -> None:
    """connect() can override the hostname and port given to the constructor."""

    async def main() -> tuple[str | None, bool, int]:
        async with FakePrologix() as adapter:
            conn = _AsyncIPConnection("192.0.2.1", 1)  # The constructor address is never used
            await conn.connect("127.0.0.1", adapter.port)
            try:
                return conn.hostname, conn.port == adapter.port, adapter.connections
            finally:
                await conn.disconnect()

    assert run(main()) == ("127.0.0.1", True, 1)


def test_read_length() -> None:
    """A fixed number of bytes can be read."""

    async def main() -> bytes:
        async with FakePrologix({b"ping": b"abcdef"}) as adapter:
            async with _AsyncIPConnection("127.0.0.1", adapter.port) as conn:
                await conn.write(b"ping\n")
                return await conn.read(length=4)

    assert run(main()) == b"abcd"


def test_read_requires_length_or_eol_character() -> None:
    """Either the number of bytes or the eol character must be given."""

    async def main() -> None:
        async with FakePrologix() as adapter:
            async with _AsyncIPConnection("127.0.0.1", adapter.port) as conn:
                await conn.read()

    with pytest.raises(TypeError, match="Either specify"):
        run(main())


@pytest.mark.parametrize(
    "method, args",
    [
        ("write", (b"ping\n",)),
        ("read", ()),
    ],
)
def test_not_connected(method: str, args: tuple[Any, ...]) -> None:
    """Reading or writing requires a connection."""
    conn = _AsyncIPConnection("127.0.0.1", 4321)
    with pytest.raises(NotConnectedError):
        run(getattr(conn, method)(*args))


@pytest.mark.parametrize("disconnect_fails", [False, True])
def test_connection_reset_during_write(disconnect_fails: bool) -> None:
    """A connection reset during a write disconnects and raises ConnectionLostError, even if disconnecting fails."""

    async def main() -> bool:
        async with FakePrologix() as adapter:
            conn = _AsyncIPConnection("127.0.0.1", adapter.port)
            await conn.connect()
            writer = _writer(conn)
            writer.write = Mock(side_effect=ConnectionResetError)  # type: ignore[method-assign]
            if disconnect_fails:
                conn.disconnect = AsyncMock(side_effect=OSError)  # type: ignore[method-assign]
            try:
                with pytest.raises(ConnectionLostError, match="Connection lost"):
                    await conn.write(b"ping\n")
                return conn.is_connected
            finally:
                writer.close()

    # If disconnect() fails, the connection is not cleaned up, but the error is still the same
    assert run(main()) is disconnect_fails


@pytest.mark.parametrize("disconnect_fails", [False, True])
def test_host_closes_connection_during_read(disconnect_fails: bool) -> None:
    """If the host closes the connection without sending anything, the connection is closed."""

    async def main() -> bool:
        server, port = await _serve_once(b"")
        async with server:
            conn = _AsyncIPConnection("127.0.0.1", port)
            await conn.connect()
            writer = _writer(conn)
            if disconnect_fails:
                conn.disconnect = AsyncMock(side_effect=OSError)  # type: ignore[method-assign]
            try:
                with pytest.raises(ConnectionLostError, match="did not reply"):
                    await conn.read(eol_character=b"\n")
                return conn.is_connected
            finally:
                writer.close()

    assert run(main()) is disconnect_fails


def test_read_waiting_for_a_closed_connection() -> None:
    """A read waiting for the lock fails, if the connection was closed by the read in front of it."""

    async def main() -> tuple[bytes | BaseException, bytes | BaseException]:
        async with FakePrologix() as adapter:  # never replies
            conn = _AsyncIPConnection("127.0.0.1", adapter.port, timeout=2)
            await conn.connect()
            first = asyncio.create_task(conn.read(eol_character=b"\n"))
            second = asyncio.create_task(conn.read(eol_character=b"\n"))
            await asyncio.sleep(0.1)  # Both reads are running, the second is waiting for the lock
            adapter.drop_connections()
            return await asyncio.gather(first, second, return_exceptions=True)

    first, second = run(main())
    assert isinstance(first, ConnectionLostError)
    assert isinstance(second, NotConnectedError)


def test_connect_refused() -> None:
    """A host that does not listen on the port refuses the connection."""
    conn = _AsyncIPConnection("127.0.0.1", _closed_port())
    with pytest.raises(ConnectionRefusedError, match="refused to connect"):
        run(conn.connect())
    assert not conn.is_connected


def test_connect_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """A host that does not answer raises a NetworkError after the timeout."""

    async def open_connection(**_kwargs: Any) -> None:
        await asyncio.sleep(10)

    monkeypatch.setattr(asyncio, "open_connection", open_connection)
    conn = _AsyncIPConnection("192.0.2.1", 1234, timeout=0.1)
    with pytest.raises(NetworkError, match="Timeout"):
        run(conn.connect())


@pytest.mark.parametrize(
    "error_number, error",
    [
        (errno.ENETUNREACH, NetworkError),
        (errno.EHOSTUNREACH, NetworkError),
        (errno.EACCES, PermissionError),  # Any other error is passed on
    ],
)
def test_connect_error(monkeypatch: pytest.MonkeyPatch, error_number: int, error: type[Exception]) -> None:
    """Network errors during connect are translated or passed on."""

    async def open_connection(**_kwargs: Any) -> None:
        raise OSError(error_number, os.strerror(error_number))

    monkeypatch.setattr(asyncio, "open_connection", open_connection)
    conn = _AsyncIPConnection("192.0.2.1", 1234)
    with pytest.raises(error):
        run(conn.connect())


@pytest.mark.parametrize(
    "error_number, raises",
    [
        (errno.ENOTCONN, False),  # The socket is already gone, so the EOF cannot be sent. This is fine.
        (errno.EIO, True),
    ],
)
def test_disconnect_flush_error(error_number: int, raises: bool) -> None:
    """Errors while flushing the buffers are passed on, unless the socket is gone, but the connection is cleared."""

    async def main() -> bool:
        async with FakePrologix() as adapter:
            conn = _AsyncIPConnection("127.0.0.1", adapter.port)
            await conn.connect()
            writer = _writer(conn)
            writer.write_eof = Mock(side_effect=OSError(error_number, os.strerror(error_number)))  # type: ignore
            try:
                if raises:
                    with pytest.raises(OSError):
                        await conn.disconnect()
                else:
                    await conn.disconnect()
            finally:
                writer.close()
            return conn.is_connected

    assert run(main()) is False


def test_shared_connection_properties() -> None:
    """The properties reflect the constructor arguments."""
    conn = AsyncSharedIPConnection("127.0.0.1", 4321)
    assert (conn.hostname, conn.port, conn.timeout) == ("127.0.0.1", 4321, DEFAULT_WAIT_TIMEOUT)
    assert str(conn) == "AsyncSharedIPConnection(127.0.0.1:4321)"


@pytest.mark.parametrize(
    "method, args",
    [
        ("write", (b"ping\n",)),
        ("read", ()),
        ("disconnect", ()),  # Disconnecting is allowed and does nothing
    ],
)
def test_shared_connection_not_connected(method: str, args: tuple[Any, ...]) -> None:
    """A shared connection without a connection from the pool cannot read or write."""
    conn = AsyncSharedIPConnection("127.0.0.1", 4321)
    if method == "disconnect":
        run(conn.disconnect())
    else:
        with pytest.raises(NotConnectedError):
            run(getattr(conn, method)(*args))
    with pytest.raises(NotConnectedError):
        _ = conn.meta


def test_shared_connection_refused() -> None:
    """A failed connect removes the connection from the pool."""
    conn = AsyncSharedIPConnection("127.0.0.1", _closed_port())
    with pytest.raises(ConnectionRefusedError):
        run(conn.connect())
    assert not _AsyncIPConnectionPool._connections  # pylint: disable=protected-access


def test_failed_connect_keeps_connection_of_other_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    """If a client fails to connect, the pooled connection is kept for the clients already connected."""

    async def main() -> bytes:
        async with FakePrologix({b"ping": b"pong\n"}) as adapter:
            async with AsyncSharedIPConnection("127.0.0.1", adapter.port) as first:
                second = AsyncSharedIPConnection("127.0.0.1", adapter.port)
                with monkeypatch.context() as patch:
                    patch.setattr(_AsyncIPConnection, "connect", AsyncMock(side_effect=RuntimeError("boom")))
                    with pytest.raises(RuntimeError, match="boom"):
                        await second.connect()
                assert ("127.0.0.1", adapter.port) in _AsyncIPConnectionPool._connections  # pylint: disable=W0212
                await first.write(b"ping\n")
                return await first.read(eol_character=b"\n")

    assert run(main()) == b"pong\n"


def test_pool_ignores_unknown_connections() -> None:
    """Disconnecting from a connection, that is not in the pool, does nothing."""

    async def main() -> None:
        client = AsyncSharedIPConnection("127.0.0.1", 4321)
        await _AsyncIPConnectionPool.disconnect("127.0.0.1", 4321, client)
        await _AsyncPooledIPConnection("127.0.0.1", 4321).disconnect_client(client)

    run(main())


def test_disconnect_while_another_client_connects() -> None:
    """
    If a client connects while the last client is waiting to disconnect, the connection stays open for the new
    client.
    """

    async def main() -> tuple[bytes, int]:
        async with FakePrologix({b"ping": b"pong\n"}) as adapter:
            first = AsyncSharedIPConnection("127.0.0.1", adapter.port)
            second = AsyncSharedIPConnection("127.0.0.1", adapter.port)
            await first.connect()
            pooled = _AsyncIPConnectionPool._connections[("127.0.0.1", adapter.port)]  # pylint: disable=W0212
            async with pooled._AsyncPooledIPConnection__lock:  # type: ignore[attr-defined]  # pylint: disable=W0212
                disconnecting = asyncio.create_task(first.disconnect())
                await asyncio.sleep(0)  # first is now waiting for the lock
                connecting = asyncio.create_task(second.connect())
                await asyncio.sleep(0)  # second has registered and is waiting for the lock
            await disconnecting
            await connecting
            try:
                await second.write(b"ping\n")
                return await second.read(eol_character=b"\n"), adapter.connections
            finally:
                await second.disconnect()

    assert run(main()) == (b"pong\n", 1)
