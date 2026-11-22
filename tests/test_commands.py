"""Tests for the commands sent to the Prologix adapter and the parsing of its replies."""

import socket
from typing import Any

import pytest

from prologix_gpib_async import (
    AsyncPrologixGpibEthernetController,
    AsyncPrologixGpibEthernetDevice,
    AsyncSharedIPConnection,
    DeviceMode,
    EosMode,
    RqsMask,
)
from prologix_gpib_async.prologix_gpib_async import AsyncPrologixGpib

from .fake_prologix import FakePrologix, run

VERSION = b"Prologix GPIB-ETHERNET Controller version 01.06.06.00"


def _controller(adapter: FakePrologix, **kwargs: Any) -> AsyncPrologixGpibEthernetController:
    kwargs = {"pad": 22, "timeout": 0.5, "ethernet_timeout": 0.5} | kwargs
    return AsyncPrologixGpibEthernetController("127.0.0.1", port=adapter.port, **kwargs)


def _device(adapter: FakePrologix, **kwargs: Any) -> AsyncPrologixGpibEthernetDevice:
    return AsyncPrologixGpibEthernetDevice("127.0.0.1", port=adapter.port, pad=5, ethernet_timeout=0.5, **kwargs)


async def _sync(gpib: AsyncPrologixGpib) -> None:
    """
    The writes do not wait for the adapter. Query the version, so that all lines sent before have been received
    by the fake adapter once the reply arrives.
    """
    assert await gpib.version() == VERSION.decode()


def _closed_port() -> int:
    """Returns a port on localhost, that nobody listens to."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
        return port


@pytest.mark.parametrize(
    "method, args, command, reply, expected",
    [
        ("get_device_mode", (), b"++mode", b"1", DeviceMode.CONTROLLER),
        ("get_read_after_write", (), b"++auto", b"1", True),
        ("get_eoi", (), b"++eoi", b"0", False),
        ("get_eos_mode", (), b"++eos", b"2", EosMode.APPEND_LF),
        ("get_eot", (), b"++eot_enable", b"1", True),
        ("get_eot_char", (), b"++eot_char", b"10", "\n"),
        ("get_save_config", (), b"++savecfg", b"0", False),
        ("get_address", (), b"++addr", b"22", {"pad": 22, "sad": 0}),
        ("get_address", (), b"++addr", b"22 96", {"pad": 22, "sad": 96}),
        ("serial_poll", (), b"++spoll", b"16", 16),
        ("serial_poll", (5,), b"++spoll 5", b"17", 17),
        ("serial_poll", (5, 96), b"++spoll 5 96", b"18", 18),
        ("test_srq", (), b"++srq", b"1", True),
        ("version", (), b"++ver", VERSION, VERSION.decode()),
    ],
)
def test_controller_query(
    method: str, args: tuple[Any, ...], command: bytes, reply: bytes, expected: Any
) -> None:  # pylint: disable=too-many-arguments
    """The queries send the command and parse the reply without the trailing b"\\r\\n"."""

    async def main() -> Any:
        async with FakePrologix({command: reply + b"\r\n"}) as adapter:
            async with _controller(adapter) as gpib:
                return await getattr(gpib, method)(*args)

    assert run(main()) == expected


@pytest.mark.parametrize(
    "method, args, command",
    [
        ("set_read_after_write", (True,), b"++auto 1"),
        ("set_address", (5,), b"++addr 5"),
        ("set_address", (5, 96), b"++addr 5 96"),
        ("set_eoi", (False,), b"++eoi 0"),
        ("set_eos_mode", (EosMode.APPEND_CR,), b"++eos 1"),
        ("set_eot", (True,), b"++eot_enable 1"),
        ("set_eot_char", (b"\x80",), b"++eot_char 128"),
        ("remote_enable", (), b"++llo"),
        ("remote_enable", (False,), b"++loc"),
        ("timeout", (0.2,), b"++read_tmo_ms 200"),
        ("timeout", (5,), b"++read_tmo_ms 3000"),  # The adapter supports at most 3000 ms
        ("ibloc", (), b"++loc"),
        ("interface_clear", (), b"++ifc"),
        ("clear", (), b"++clr"),
        ("set_save_config", (True,), b"++savecfg 1"),
        ("write", (b"VOLT 1.5+\r\n\x1b",), b"VOLT 1.5\x1b+\x1b\r\x1b\n\x1b\x1b"),  # escape control characters
    ],
)
def test_controller_command(method: str, args: tuple[Any, ...], command: bytes) -> None:
    """The setters and commands send the right line to the adapter."""

    async def main() -> list[bytes]:
        async with FakePrologix({b"++ver": VERSION + b"\r\n"}) as adapter:
            async with _controller(adapter) as gpib:
                await _sync(gpib)
                adapter.lines.clear()
                await getattr(gpib, method)(*args)
                await _sync(gpib)
            return adapter.lines

    # The fake adapter splits the escaped newline of write(), so compare the stream of bytes
    assert b"\n".join(run(main())) == command + b"\n++ver"


def test_settings_are_only_sent_on_change() -> None:
    """The cached state of the adapter avoids sending the configuration again with every command."""

    async def main() -> list[bytes]:
        async with FakePrologix({b"++ver": VERSION + b"\r\n"}) as adapter:
            async with _controller(adapter) as gpib:
                await gpib.write(b"*RST")
                await _sync(gpib)
                adapter.lines.clear()
                await gpib.write(b"*CLS")
                await _sync(gpib)
            return adapter.lines

    assert run(main()) == [b"*CLS", b"++ver"]


def test_trigger_with_secondary_address() -> None:
    """Without a list of devices, the selected device is triggered by its primary and secondary address."""

    async def main() -> list[bytes]:
        async with FakePrologix({b"++ver": VERSION + b"\r\n"}) as adapter:
            async with _controller(adapter, sad=96) as gpib:
                await gpib.trigger()
                await _sync(gpib)
            return adapter.lines

    lines = run(main())
    assert b"++addr 22 96" in lines
    assert lines[-2] == b"++trg 22 96"


def test_read_length() -> None:
    """A fixed number of bytes can be read."""

    async def main() -> bytes:
        async with FakePrologix({b"++read eoi": b"abcdef"}) as adapter:
            async with _controller(adapter) as gpib:
                return await gpib.read(length=3)

    assert run(main()) == b"abc"


def test_read_until_eot_character() -> None:
    """If the adapter appends the EOT character, the read ends at that character."""

    async def main() -> bytes:
        async with FakePrologix({b"++read eoi": b"1.23\n4\x80"}) as adapter:
            async with _controller(adapter) as gpib:
                await gpib.set_eot_char(b"\x80")
                await gpib.set_eot(True)
                return await gpib.read()

    assert run(main()) == b"1.23\n4\x80"


def test_read_after_write_without_polling() -> None:
    """With read-after-write enabled, read(force_poll=False) does not ask the device to talk."""

    async def main() -> tuple[bytes, list[bytes]]:
        async with FakePrologix({b"*IDN?": b"ACME\n"}) as adapter:
            async with _controller(adapter) as gpib:
                await gpib.set_read_after_write(True)
                await gpib.write(b"*IDN?")
                return await gpib.read(force_poll=False), adapter.lines

    data, lines = run(main())
    assert data == b"ACME\n"
    assert b"++read eoi" not in lines


def test_wait_without_timeout() -> None:
    """Without TIMO, wait() polls until the device has set the RQS bit in its status byte."""

    async def main() -> tuple[int, list[bytes]]:
        replies: dict[bytes, bytes | list[bytes]] = {
            b"++srq": b"1\r\n",
            b"++spoll 22": [b"16\r\n", b"80\r\n"],
        }  # Only 80 has bit 6 (RQS) set
        async with FakePrologix(replies) as adapter:
            async with _controller(adapter) as gpib:
                gpib.set_wait_delay(0.1)
                status = await gpib.wait(RqsMask.RQS.value)
            return status, adapter.lines

    status, lines = run(main())
    assert status == 80
    assert lines.count(b"++spoll 22") == 2


def test_controller_properties() -> None:
    """The properties of the controller reflect the constructor arguments."""
    gpib = AsyncPrologixGpibEthernetController("127.0.0.1", port=4321, pad=22, sad=96, timeout=2, ethernet_timeout=1)
    assert (gpib.hostname, gpib.port, gpib.pad, gpib.sad) == ("127.0.0.1", 4321, 22, 96)
    assert gpib.get_connection_timeout() == 3  # GPIB + network timeout
    assert str(gpib) == "Prologix GPIB controller of device (22,96) at AsyncSharedIPConnection(127.0.0.1:4321)"


def test_base_class_str() -> None:
    """The base class names the connection."""
    conn = AsyncSharedIPConnection("127.0.0.1", 4321)
    gpib = AsyncPrologixGpib(
        conn,
        pad=22,
        device_mode=DeviceMode.CONTROLLER,
        sad=0,
        timeout=3,
        send_eoi=True,
        wait_delay=0.25,
        eos_mode=EosMode.APPEND_NONE,
    )
    assert str(gpib) == "Prologix GPIB at AsyncSharedIPConnection(127.0.0.1:4321)"


def test_device_properties() -> None:
    """The properties of the device reflect the constructor arguments."""
    gpib = AsyncPrologixGpibEthernetDevice("127.0.0.1", port=4321, pad=5, sad=97)
    assert (gpib.hostname, gpib.port, gpib.pad, gpib.sad) == ("127.0.0.1", 4321, 5, 97)
    assert str(gpib) == "Prologix GPIB device (5,97) at AsyncSharedIPConnection(127.0.0.1:4321)"


def test_device_configuration() -> None:
    """A device configures the adapter in device mode."""

    async def main() -> list[bytes]:
        async with FakePrologix({b"++ver": VERSION + b"\r\n"}) as adapter:
            async with _device(adapter) as gpib:
                await _sync(gpib)
            return adapter.lines

    lines = run(main())
    assert lines[0] == b"++savecfg 0"
    assert b"++mode 0" in lines
    assert b"++addr 5" in lines


@pytest.mark.parametrize(
    "method, args, command, reply, expected",
    [
        ("get_status", (), b"++status", b"16", 16),
        ("get_listen_only", (), b"++lon", b"1", True),
    ],
)
def test_device_query(
    method: str, args: tuple[Any, ...], command: bytes, reply: bytes, expected: Any
) -> None:  # pylint: disable=too-many-arguments
    """The queries only available in device mode."""

    async def main() -> Any:
        async with FakePrologix({command: reply + b"\r\n"}) as adapter:
            async with _device(adapter) as gpib:
                return await getattr(gpib, method)(*args)

    assert run(main()) == expected


@pytest.mark.parametrize(
    "method, args, command",
    [
        ("set_status", (16,), b"++status 16"),
        ("set_listen_only", (True,), b"++lon 1"),
    ],
)
def test_device_command(method: str, args: tuple[Any, ...], command: bytes) -> None:
    """The commands only available in device mode."""

    async def main() -> list[bytes]:
        async with FakePrologix({b"++ver": VERSION + b"\r\n"}) as adapter:
            async with _device(adapter) as gpib:
                await getattr(gpib, method)(*args)
                await _sync(gpib)
            return adapter.lines

    assert run(main())[-2] == command


@pytest.mark.parametrize(
    "method, args",
    [
        ("set_listen_only", (True,)),
        ("get_listen_only", ()),
        ("set_status", (16,)),
        ("get_status", ()),
    ],
)
def test_controller_rejects_device_commands(method: str, args: tuple[Any, ...]) -> None:
    """Commands of the device mode are not available in controller mode."""
    gpib = AsyncPrologixGpibEthernetController("127.0.0.1", pad=22)
    with pytest.raises(TypeError, match="Not supported in controller mode"):
        run(getattr(gpib, method)(*args))


@pytest.mark.parametrize(
    "method, args",
    [
        ("set_read_after_write", (True,)),
        ("get_read_after_write", ()),
        ("clear", ()),
        ("interface_clear", ()),
        ("remote_enable", ()),
        ("ibloc", ()),
        ("read", ()),
        ("timeout", (1,)),
        ("serial_poll", ()),
        ("test_srq", ()),
        ("trigger", ()),
        ("wait", (RqsMask.RQS.value,)),
    ],
)
def test_device_rejects_controller_commands(method: str, args: tuple[Any, ...]) -> None:
    """Commands of the controller mode are not available in device mode."""
    gpib = AsyncPrologixGpibEthernetDevice("127.0.0.1", pad=5)
    with pytest.raises(TypeError, match="Not supported in device mode"):
        run(getattr(gpib, method)(*args))


def test_failed_connect_releases_the_connection() -> None:
    """If the adapter cannot be reached, the error is passed on and the connection is returned to the pool."""

    async def main() -> None:
        gpib = AsyncPrologixGpibEthernetController("127.0.0.1", port=_closed_port(), pad=22)
        await gpib.connect()

    with pytest.raises(ConnectionRefusedError):
        run(main())


def test_close_is_an_alias_for_disconnect() -> None:
    """close() disconnects from the adapter."""

    async def main() -> None:
        async with FakePrologix() as adapter:
            gpib = _controller(adapter)
            await gpib.connect()
            await gpib.close()
            with pytest.raises(ConnectionError):
                await gpib.write(b"*IDN?")

    run(main())
