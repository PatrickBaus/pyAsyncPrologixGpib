"""
This file contains classes for the Prologix GPIB Ethernet adapter.
The manual can be found here: http://prologix.biz/downloads/PrologixGpibEthernetManual.pdf
"""
from .ip_connection import AsyncSharedIPConnection
from .prologix_gpib_async import EosMode
from .prologix_gpib_base import AsyncPrologixGpibController, AsyncPrologixGpibDevice


class AsyncPrologixGpibEthernetController(AsyncPrologixGpibController):
    """
    Acts as the GPIB bus controller. It is a convenience class that uses the `AsyncSharedIPConnection` and
    simplifies the setup of an `AsyncPrologixGpibController`.
    """

    @property
    def hostname(self) -> str:
        """
        Returns
        -------
        str
            The hostname of the device.
        """
        return self._conn.hostname

    @property
    def port(self) -> int:
        """
        Returns
        -------
        int
            The port of the ethernet connection.
        """
        return self._conn.port

    def __init__(  # pylint: disable=too-many-arguments
        self,
        hostname: str,
        pad: int,
        port: int = 1234,
        sad: int = 0,
        timeout: float = 3,  # in seconds
        send_eoi: bool = True,
        eos_mode: EosMode = EosMode.APPEND_NONE,
        ethernet_timeout: float = 1,  # in seconds
        wait_delay: float = 0.25,  # in s seconds
    ) -> None:
        conn = AsyncSharedIPConnection(hostname=hostname, port=port, timeout=(timeout + ethernet_timeout))  # in seconds
        super().__init__(
            conn=conn,
            pad=pad,
            sad=sad,
            timeout=timeout,
            send_eoi=send_eoi,
            eos_mode=eos_mode,
            wait_delay=wait_delay,
        )


class AsyncPrologixGpibEthernetDevice(AsyncPrologixGpibDevice):
    """
    Acts as a GPIB device on the bus. It is a convenience class that uses the `AsyncSharedIPConnection` and
    simplifies the setup of an `AsyncPrologixGpibDevice`.
    """

    @property
    def hostname(self) -> str:
        """
        Returns
        -------
        str
            The hostname of the device.
        """
        return self._conn.hostname

    @property
    def port(self) -> int:
        """
        Returns
        -------
        int
            The port of the ethernet connection.
        """
        return self._conn.port

    def __init__(  # pylint: disable=too-many-arguments
        self,
        hostname: str,
        pad: int,
        port: int = 1234,
        sad: int = 0,
        send_eoi: bool = True,
        eos_mode: EosMode = EosMode.APPEND_NONE,
        ethernet_timeout: float = 1,  # in seconds
        wait_delay: float = 0.25,  # in seconds
    ) -> None:
        conn = AsyncSharedIPConnection(hostname=hostname, port=port, timeout=ethernet_timeout)  # in seconds
        super().__init__(
            conn=conn,
            pad=pad,
            sad=sad,
            send_eoi=send_eoi,
            eos_mode=eos_mode,
            wait_delay=wait_delay,
        )
