"""
A minimal fake Prologix GPIB-ETHERNET adapter for tests. It records every line it receives and answers
commands from a configurable reply table.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine, Mapping
from types import TracebackType
from typing import Any


class FakePrologix:
    """
    A TCP server that records received lines and replies to known commands.

    Parameters
    ----------
    replies: dict
        Maps a received line (without the trailing b"\\n") to the raw bytes to send back. Use None to send nothing.
        A list of replies is answered one after the other, the last reply is repeated.
    """

    def __init__(self, replies: Mapping[bytes, bytes | list[bytes] | None] | None = None) -> None:
        self.replies: dict[bytes, bytes | list[bytes] | None] = {} if replies is None else dict(replies)
        self.lines: list[bytes] = []
        self.connections = 0
        self.port: int = 0
        self.__server: asyncio.Server | None = None
        self.__writers: list[asyncio.StreamWriter] = []

    async def __aenter__(self) -> FakePrologix:
        self.__server = await asyncio.start_server(self.__handle, "127.0.0.1", 0)
        self.port = self.__server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, traceback: TracebackType | None
    ) -> None:
        self.drop_connections()
        assert self.__server is not None
        self.__server.close()
        await self.__server.wait_closed()

    def drop_connections(self) -> None:
        """Close all client connections, simulating an adapter reboot or network loss."""
        for writer in self.__writers:
            writer.close()
        self.__writers.clear()

    async def __handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.connections += 1
        self.__writers.append(writer)
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                line = line.rstrip(b"\n")
                self.lines.append(line)
                reply = self.replies.get(line)
                if isinstance(reply, list):
                    reply = reply.pop(0) if len(reply) > 1 else reply[0]
                if reply is not None:
                    writer.write(reply)
                    await writer.drain()
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            writer.close()


def run[T](coro: Coroutine[Any, Any, T], timeout: float = 5) -> T:
    """Run a coroutine with a hard timeout, so a broken test fails instead of hanging."""

    async def guarded() -> T:
        async with asyncio.timeout(timeout):
            return await coro

    return asyncio.run(guarded())
