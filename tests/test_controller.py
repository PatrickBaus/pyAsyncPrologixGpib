"""Tests for the GPIB controller against a fake Prologix adapter."""

import asyncio
from collections.abc import Sequence
from typing import Any

import pytest

from prologix_gpib_async import AsyncPrologixGpibEthernetController, RqsMask
from prologix_gpib_async.prologix_gpib_async import GpibAddress

from .fake_prologix import FakePrologix, run


def test_read_until_character_without_newline() -> None:
    """read(character=...) must stop at that character, even if the device never sends a newline."""

    async def main() -> bytes:
        async with FakePrologix({b"++read 59": b"1.234;"}) as adapter:
            async with AsyncPrologixGpibEthernetController(
                "127.0.0.1", port=adapter.port, pad=22, timeout=0.5, ethernet_timeout=0.5
            ) as gpib:
                return await gpib.read(character=b";")

    assert run(main()) == b"1.234;"


def test_read_default_uses_newline() -> None:
    """Without a character, the read still ends at the default separator."""

    async def main() -> bytes:
        async with FakePrologix({b"++read eoi": b"1.234\n"}) as adapter:
            async with AsyncPrologixGpibEthernetController(
                "127.0.0.1", port=adapter.port, pad=22, timeout=0.5, ethernet_timeout=0.5
            ) as gpib:
                return await gpib.read()

    assert run(main()) == b"1.234\n"


def _controller(adapter: FakePrologix) -> AsyncPrologixGpibEthernetController:
    return AsyncPrologixGpibEthernetController(
        "127.0.0.1", port=adapter.port, pad=22, timeout=0.5, ethernet_timeout=0.5
    )


def test_connect_disables_eeprom_before_configuring() -> None:
    """++savecfg 0 must be the first command, so that the configuration is not written to the EEPROM."""

    async def main() -> list[bytes]:
        async with FakePrologix() as adapter:
            async with _controller(adapter):
                pass
            return adapter.lines

    lines = run(main())
    assert lines[0] == b"++savecfg 0"
    assert b"++addr 22" in lines


def test_reset_resends_configuration() -> None:
    """After ++rst the adapter loads its EEPROM settings, so the configuration must be sent again."""

    async def main() -> list[bytes]:
        async with FakePrologix() as adapter:
            async with _controller(adapter) as gpib:
                await gpib.reset()
                await asyncio.sleep(0.1)
                adapter.lines.clear()
                await gpib.write(b"*IDN?")
                await asyncio.sleep(0.1)  # let the server process the lines
            return adapter.lines

    lines = run(main())
    assert lines[0] == b"++savecfg 0"
    assert b"++mode 1" in lines
    assert b"++addr 22" in lines
    assert lines[-1] == b"*IDN?"


def test_reconnect_resends_configuration() -> None:
    """After the connection was lost, e.g. due to an adapter reboot, the configuration must be sent again."""

    async def main() -> tuple[int, list[bytes]]:
        async with FakePrologix() as adapter:
            async with _controller(adapter) as gpib:
                adapter.drop_connections()
                with pytest.raises(ConnectionError):
                    await gpib.read()
                adapter.lines.clear()
                await gpib.connect()
                await asyncio.sleep(0.1)
                lines = list(adapter.lines)
            return adapter.connections, lines

    connections, lines = run(main())
    assert connections == 2
    assert lines[0] == b"++savecfg 0"
    assert b"++addr 22" in lines


@pytest.mark.parametrize(
    "devices, command",
    [
        ((), b"++trg 22"),
        ((10,), b"++trg 10"),
        ((10, (22, 96)), b"++trg 10 22 96"),
        ([[5, 100], 7], b"++trg 5 100 7"),
    ],
)
def test_trigger_addresses(devices: Sequence[GpibAddress], command: bytes) -> None:
    """trigger() accepts primary addresses and (pad, sad) pairs as tuples or lists."""

    async def main() -> list[bytes]:
        async with FakePrologix() as adapter:
            async with _controller(adapter) as gpib:
                await gpib.trigger(devices)
                await asyncio.sleep(0.1)
            return adapter.lines

    assert run(main())[-1] == command


@pytest.mark.parametrize("device", ["22", (1, 2, 3), [4]])
def test_trigger_rejects_invalid_address(device: Any) -> None:
    """Anything other than a pad or a (pad, sad) pair is rejected."""

    async def main() -> None:
        async with FakePrologix() as adapter:
            async with _controller(adapter) as gpib:
                await gpib.trigger([device])

    with pytest.raises(TypeError, match="Invalid GPIB address"):
        run(main())


def test_wait_requires_rqs() -> None:
    """wait() names the missing flag in its error message."""

    async def main() -> None:
        async with FakePrologix() as adapter:
            async with _controller(adapter) as gpib:
                await gpib.wait(RqsMask.TIMO.value)

    with pytest.raises(ValueError, match=r"^RqsMask\.RQS not set$"):
        run(main())


def test_wait_returns_status_byte_on_srq() -> None:
    """wait() polls the SRQ line and returns the status byte once the device requests service."""

    async def main() -> int:
        replies = {b"++srq": b"1\r\n", b"++spoll 22": b"80\r\n"}  # 80 = 0b1010000, bit 6 (RQS) set
        async with FakePrologix(replies) as adapter:
            async with _controller(adapter) as gpib:
                gpib.set_wait_delay(0.1)
                return await gpib.wait((RqsMask.RQS | RqsMask.TIMO).value)

    assert run(main()) == 80


def test_wait_times_out_without_srq() -> None:
    """With TIMO set, wait() gives up after the timeout."""

    async def main() -> None:
        async with FakePrologix({b"++srq": b"0\r\n"}) as adapter:
            async with _controller(adapter) as gpib:
                gpib.set_wait_delay(0.1)
                with pytest.raises(TimeoutError):
                    await gpib.wait((RqsMask.RQS | RqsMask.TIMO).value)

    run(main())


def test_cancelled_wait_leaves_no_task_behind() -> None:
    """Cancelling wait() while it polls the adapter must not leave an orphaned sleep task running."""

    async def main() -> list[asyncio.Task[Any]]:
        async with FakePrologix() as adapter:  # never answers ++srq, so wait() is stuck in the poll
            async with _controller(adapter) as gpib:
                gpib.set_wait_delay(0.5)
                with pytest.raises(TimeoutError):
                    async with asyncio.timeout(0.2):
                        await gpib.wait(RqsMask.RQS.value)
                await asyncio.sleep(0)
                return [
                    task
                    for task in asyncio.all_tasks()
                    if not task.done() and task.get_coro().__qualname__ == "sleep"  # type: ignore[union-attr]
                ]

    assert run(main()) == []
