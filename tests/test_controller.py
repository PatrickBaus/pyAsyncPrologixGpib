"""Tests for the GPIB controller against a fake Prologix adapter."""

import asyncio

import pytest

from prologix_gpib_async import AsyncPrologixGpibEthernetController

from .fake_prologix import FakePrologix, run


def test_read_until_character_without_newline():
    """read(character=...) must stop at that character, even if the device never sends a newline."""

    async def main():
        async with FakePrologix({b"++read 59": b"1.234;"}) as adapter:
            async with AsyncPrologixGpibEthernetController(
                "127.0.0.1", port=adapter.port, pad=22, timeout=0.5, ethernet_timeout=0.5
            ) as gpib:
                return await gpib.read(character=b";")

    assert run(main()) == b"1.234;"


def test_read_default_uses_newline():
    """Without a character, the read still ends at the default separator."""

    async def main():
        async with FakePrologix({b"++read eoi": b"1.234\n"}) as adapter:
            async with AsyncPrologixGpibEthernetController(
                "127.0.0.1", port=adapter.port, pad=22, timeout=0.5, ethernet_timeout=0.5
            ) as gpib:
                return await gpib.read()

    assert run(main()) == b"1.234\n"


def _controller(adapter):
    return AsyncPrologixGpibEthernetController(
        "127.0.0.1", port=adapter.port, pad=22, timeout=0.5, ethernet_timeout=0.5
    )


def test_connect_disables_eeprom_before_configuring():
    """++savecfg 0 must be the first command, so that the configuration is not written to the EEPROM."""

    async def main():
        async with FakePrologix() as adapter:
            async with _controller(adapter):
                pass
            return adapter.lines

    lines = run(main())
    assert lines[0] == b"++savecfg 0"
    assert b"++addr 22" in lines


def test_reset_resends_configuration():
    """After ++rst the adapter loads its EEPROM settings, so the configuration must be sent again."""

    async def main():
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


def test_reconnect_resends_configuration():
    """After the connection was lost, e.g. due to an adapter reboot, the configuration must be sent again."""

    async def main():
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
