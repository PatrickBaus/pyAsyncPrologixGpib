"""Tests for the GPIB controller against a fake Prologix adapter."""

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
