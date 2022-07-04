"""
This file contains the base classes of a GPIB controller or device.
"""
from __future__ import annotations

from .ip_connection import AsyncSharedIPConnection
from .prologix_gpib_async import AsyncPrologixGpib, DeviceMode, EosMode


class AsyncPrologixGpibController(AsyncPrologixGpib):
    """
    A Prologix GPIB controller with a custom connection object. It acts as a controller on the GPIB bus.
    """

    def __init__(  # pylint: disable=too-many-arguments
        self,
        conn: AsyncSharedIPConnection,
        pad: int,
        sad: int = 0,
        timeout: float = 10,  # in seconds
        send_eoi: bool = True,
        eos_mode: EosMode = EosMode.APPEND_NONE,
        wait_delay: float = 0.25,  # in seconds
    ) -> None:
        """
        Parameters
        ----------
        conn: AsyncSharedIPConnection
            Either a connection from the pool or a standalone connection.
        pad: int
            Primary address
        sad: int
            Secondary address
        timeout: float, default = 10
            Timeout for GPIB operations in seconds. The default is the same as used by linux-gpib.
        send_eoi: bool
            Assert EOI on write
        eos_mode: bool:
            End-of-string termination
        wait_delay: float
            Number of ms to wait in between serial polling a device when waiting.
        """
        super().__init__(
            conn=conn,
            pad=pad,
            sad=sad,
            device_mode=DeviceMode.CONTROLLER,
            timeout=timeout,
            send_eoi=send_eoi,
            eos_mode=eos_mode,
            wait_delay=wait_delay,
        )

    def __str__(self) -> str:
        return f"Prologix GPIB controller of device ({self.pad},{self.sad}) at {self._conn}"

    async def set_listen_only(self, enable: bool) -> None:
        """
        Not available in controller mode.
        """
        raise TypeError("Not supported in controller mode")

    async def get_listen_only(self) -> bool:
        """
        Not available in controller mode.
        """
        raise TypeError("Not supported in controller mode")

    async def set_status(self, value: int) -> None:
        """
        Not available in controller mode.
        """
        raise TypeError("Not supported in controller mode")

    async def get_status(self) -> int:
        """
        Not available in controller mode.
        """
        raise TypeError("Not supported in controller mode")


class AsyncPrologixGpibDevice(AsyncPrologixGpib):
    """
    A Prologix GPIB device with a custom connection object. It acts as a device on the GPIB bus.
    """

    def __init__(  # pylint: disable=too-many-arguments
        self,
        conn: AsyncSharedIPConnection,
        pad: int,
        sad: int = 0,
        send_eoi: bool = True,
        eos_mode: EosMode = EosMode.APPEND_NONE,
        wait_delay: float = 0.25,  # in seconds
    ) -> None:
        """
        Parameters
        ----------
        conn: AsyncSharedIPConnection
            Either a connection from the pool or a standalone connection.
        pad: int
            Primary address
        sad: int
            Secondary address
        send_eoi: bool
            Assert EOI on write
        eos_mode: bool:
            End-of-string termination
        wait_delay: float
            Number of seconds to wait in between serial polling a device when waiting..
        """
        super().__init__(
            conn=conn,
            pad=pad,
            sad=sad,
            device_mode=DeviceMode.DEVICE,
            timeout=3,  # in seconds. This is the GPIB read timeout. A device can not read, so leave it at the default
            send_eoi=send_eoi,
            eos_mode=eos_mode,
            wait_delay=wait_delay,
        )

    def __str__(self):
        return f"Prologix GPIB device ({self.pad},{self.sad}) at {self._conn}"

    async def set_read_after_write(self, enable: bool) -> None:
        """
        Not available in device mode.
        """
        raise TypeError("Not supported in device mode")

    async def get_read_after_write(self) -> bool:
        """
        Not available in device mode.
        """
        raise TypeError("Not supported in device mode")

    async def clear(self) -> None:
        """
        Not available in device mode.
        """
        raise TypeError("Not supported in device mode")

    async def interface_clear(self) -> None:
        """
        Not available in device mode.
        """
        raise TypeError("Not supported in device mode")

    async def remote_enable(self, enable: bool = True) -> None:
        """
        Not available in device mode.
        """
        raise TypeError("Not supported in device mode")

    async def ibloc(self) -> None:
        """
        Not available in device mode.
        """
        raise TypeError("Not supported in device mode")

    async def read(self, length: int | None = None, character: bytes | None = None, force_poll: bool = True) -> bytes:
        """
        Not available in device mode.
        """
        raise TypeError("Not supported in device mode")

    async def timeout(self, value: float) -> None:
        """
        Not available in device mode.
        """
        raise TypeError("Not supported in device mode")

    async def serial_poll(self, pad: int = 0, sad: int = 0) -> int:
        """
        Not available in device mode.
        """
        raise TypeError("Not supported in device mode")

    async def test_srq(self) -> bool:
        """
        Not available in device mode.
        """
        raise TypeError("Not supported in device mode")

    async def trigger(
        self, devices: tuple[int | tuple[int, int] | list[int], ...] | list[int | tuple[int, int] | list[int]] = ()
    ) -> None:
        """
        Not available in device mode.
        """
        raise TypeError("Not supported in device mode")

    async def wait(self, mask: int) -> int:
        """
        Not available in device mode.
        """
        raise TypeError("Not supported in device mode")

    def set_wait_delay(self, value: float) -> None:
        """
        Not available in device mode.
        """
        raise TypeError("Not supported in device mode")
