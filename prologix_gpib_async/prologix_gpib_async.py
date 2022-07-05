"""
This file implements the API used by the Prologix GPIB adapters in pure python using AsyncIO.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import TracebackType
from typing import Type

try:
    from typing import Self  # type: ignore # Python >=3.11
except ImportError:
    from typing_extensions import Self

import re  # needed to escape characters in the byte stream
from enum import Enum, Flag, unique

from .ip_connection import AsyncSharedIPConnection


@unique
class DeviceMode(Enum):
    """
    The GPIB controller can act as either a GPIB device or as a GPIB bus controller
    """

    DEVICE = 0
    CONTROLLER = 1


@unique
class EosMode(Enum):
    """
    The GPIB termination characters, select CR+LF, CR, LF or nothing at all.
    """

    APPEND_CR_LF = 0
    APPEND_CR = 1
    APPEND_LF = 2
    APPEND_NONE = 3


@unique
class RqsMask(Flag):
    """
    The bitmask used, when serial polling a GPIB device to determine if the device requests service
    (RQS) or has a timeout (TIMO).
    """

    NONE = 0
    RQS = 1 << 11
    TIMO = 1 << 14


@dataclass
class DeviceState:  # pylint: disable=too-many-instance-attributes # This is how it is. No way around it.
    """Represents the state of the Prologix adapter."""

    pad: int
    sad: int
    send_eoi: bool
    send_eot: bool
    eot_char: bytes
    eos_mode: EosMode
    timeout: float
    read_after_write: bool
    device_mode: DeviceMode


# The following characters need to be escaped according to:
# http://prologix.biz/downloads/PrologixGpibEthernetManual.pdf
translation_map = {
    b"\r": b"\x1B\r",
    b"\n": b"\x1B\n",
    b"+": b"\x1B+",
    b"\x1B": b"\x1B\x1B",
}

# Generate a regex pattern which matches either of the characters (|).
# Characters like "\n" need to be escaped when used in a regex, so we run re.escape on
# all characters first.
escape_pattern = re.compile(b"|".join(map(re.escape, translation_map.keys())))


class AsyncPrologixGpib:  # pylint: disable=too-many-public-methods
    """
    The base class used by both the Prologix GPIB controller and GPIB device.
    """

    _SEPARATOR = b"\n"  # The default separator typically used by GPIB devices

    @property
    def _conn(self) -> AsyncSharedIPConnection:
        return self.__conn

    @property
    def pad(self) -> int:
        """
        Returns
        -------
        int
            The device primary address
        """
        return self.__state.pad

    @property
    def sad(self) -> int:
        """
        Returns
        -------
        int
            The device secondary address
        """
        return self.__state.sad

    def __init__(  # pylint: disable=too-many-arguments
        self,
        conn: AsyncSharedIPConnection,
        pad: int,
        device_mode: DeviceMode,
        sad: int,
        timeout: float,
        send_eoi: bool,
        wait_delay: float,
        eos_mode: EosMode,
    ) -> None:
        """
        Parameters
        ----------
        conn: AsyncSharedIPConnection
            Either a connection from the pool or a standalone connection.
        pad: int
            Primary address
        device_mode: DeviceMode
            Run the controller either as a device or a bus controller.
        sad: int
            Secondary address
        timeout: float
            GPIB timeout for operations in seconds.
        send_eoi: bool
            Assert EOI on write
        eos_mode: bool:
            End-of-string termination
        wait_delay: float
            Number of ms to wait in between serial polling a device when waiting.
        """
        self.__conn = conn
        self.__state = DeviceState(
            pad=pad,
            sad=sad,
            send_eoi=bool(int(send_eoi)),
            send_eot=False,
            eot_char=b"\n",
            eos_mode=EosMode(eos_mode),
            timeout=timeout,
            read_after_write=False,
            device_mode=device_mode,
        )
        self.__wait_delay: float
        self.set_wait_delay(wait_delay)

    def __str__(self) -> str:
        return f"Prologix GPIB at {str(self.__conn)}"

    async def __aenter__(self) -> Self:
        await self.connect()
        return self

    async def __aexit__(
        self, exc_type: Type[BaseException] | None, exc: BaseException | None, traceback: TracebackType | None
    ) -> None:
        await self.disconnect()

    async def connect(self) -> None:
        """
        Connect to the device and configure it. By default, the configuration will not be saved to EEPROM to save
        write cycles. If you want to save it to the EEPROM run, enable it via set_save_config() once connected.
        """
        try:
            await self.__conn.connect()
            lock = self.__conn.meta.setdefault("lock", asyncio.Lock())  # either create a new lock or get the old one
            async with lock:
                await asyncio.gather(
                    self.set_save_config(False),  # Disable saving the config to EEPROM by default to save EEPROM writes
                    self.__ensure_state(),
                )
        except BaseException:  # pylint: disable=broad-except
            await self.__conn.disconnect()
            raise

    async def close(self) -> None:
        """
        This is an alias for disconnect().
        """
        await self.disconnect()

    async def disconnect(self) -> None:
        """
        Close the ip connection and flush its buffers.
        """
        await self.__conn.disconnect()

    async def __ensure_state(self) -> None:
        """
        Push the current state of the gpib device to the remote state of the controller.
        Note: Before calling this function, acquire the self.__conn.meta['lock'], to ensure, that only one gpib device
        is modifying the remote state of the controller.
        """
        jobs = []
        if self.__state.device_mode != self.__conn.meta.get("device_mode"):
            jobs.append(self.__set_device_mode(self.__state.device_mode))
        if self.__state.pad != self.__conn.meta.get("pad") or self.__state.sad != self.__conn.meta.get("sad"):
            jobs.append(self.__set_address(self.__state.pad, self.__state.sad))
        if self.__state.read_after_write != self.__conn.meta.get("read_after_write"):
            jobs.append(self.__set_read_after_write(self.__state.read_after_write))
        if self.__state.send_eoi != self.__conn.meta.get("send_eoi"):
            jobs.append(self.__set_eoi(self.__state.send_eoi))
        if self.__state.send_eot != self.__conn.meta.get("send_eot"):
            jobs.append(self.__set_eot(self.__state.send_eot))
        if self.__state.eot_char != self.__conn.meta.get("eot_char"):
            jobs.append(self.__set_eot_char(self.__state.eot_char))
        if self.__state.eos_mode != self.__conn.meta.get("eos_mode"):
            jobs.append(self.__set_eos_mode(self.__state.eos_mode))
        if self.__state.timeout != self.__conn.meta.get("timeout"):
            jobs.append(self.__timeout(self.__state.timeout))

        if jobs:
            await asyncio.gather(*jobs)

    async def __query_command(self, command: bytes) -> bytes:
        """
        Issue a Prologix command and return the result. This function will strip the b"\r\n" control sequence returned
        by the controller.
        Note: Before calling this function, acquire the self.__conn.meta['lock'], to ensure, that only one read
        request is performed.

        Parameters
        ----------
        command: bytes
            Sequence of bytes to write

        Returns
        -------
        bytes
            Sequence of bytes which was read
        """
        await self.__write(command)
        return (await self.__conn.read(eol_character=b"\n"))[:-2]  # strip the EOT characters (b"\r\n")

    @staticmethod
    def __escape_data(data: bytes) -> bytes:
        """
        The prologix adapter uses ++ to signal commands. The b"\r\n" characters are used to separate messages. In order
        to transmit these characters to the GPIB device, they need to be escaped using the ESC character (b"\x1B").
        Therefore b"\r", b"\n", b"\x1B" (27, ESC) and b"+" need to be escaped.

        Parameters
        ----------
        data: bytes
            Sequence of bytes to escape

        Returns
        -------
        bytes
            Sequence of escaped bytes
        """
        # Use a regex to match them, then replace them using a translation map
        return escape_pattern.sub(lambda match: translation_map[match.group(0)], data)

    async def __write(self, data: bytes) -> None:
        await self.__conn.write(data + b"\n")  # Append Prologix termination character

    async def write(self, data: bytes) -> None:
        """
        Send a byte string to the GPIB device. The byte string will automatically be escaped, so it is not possible to
        send commands to the GPIB controller.

        Parameters
        ----------
        data: bytes
            Sequence of bytes to write
        """
        data = self.__escape_data(data)
        async with self.__conn.meta["lock"]:
            await self.__ensure_state()
            await self.__write(data)

    async def read(self, length: int | None = None, character: bytes | None = None, force_poll: bool = True) -> bytes:
        """
        Read data until an EOI (End of Identify) was received (default), or if the character parameter is set until the
        character is received. Using the len parameter it is possible to read only a certain number of bytes.
        The underlying network protocol is a stream protocol, which does not know about the EOI of the GPIB bus. By
        default, a packet is terminated by a b"\n". If the device does not terminate its packets with either b"\r\n" or
        b"\n", consider using an EOT character, if there is no way of knowing the number of bytes returned.
        When using the "read after write" feature, force_poll can be set to False, when reading after sending a
        command.

        Parameters
        ----------
        length: int, default=None
            Number of bytes to read
        character: bytes, default=None
            An eol character
        force_poll: bool, default=True
            If True, always request the GPIB device to TALK before reading.

        Returns
        -------
        bytes
            sequence of bytes
        """
        async with self.__conn.meta["lock"]:
            await self.__ensure_state()
            if force_poll or not self.__state.read_after_write:
                if character is None:
                    await self.__write(b"++read eoi")
                else:
                    await self.__write(f"++read {ord(character):d}".encode("ascii"))

            return await self.__conn.read(
                length=length, eol_character=self.__state.eot_char if self.__state.send_eot else self._SEPARATOR
            )

    async def get_device_mode(self) -> DeviceMode:
        """
        Returns
        -------
        DeviceMode
            Configuration of the GPIB adapter
        """
        async with self.__conn.meta["lock"]:
            return DeviceMode(int(await self.__query_command(b"++mode")))

    async def set_read_after_write(self, enable: bool) -> None:
        """
        If enabled automatically triggers the instrument to TALK after each command. If set, the instrument is also
        immediately asked to TALK (enable==True) or LISTEN (enable==False).

        Parameters
        ----------
        enable: bool
            Ask the device to talk after each command if True.
        """
        async with self.__conn.meta["lock"]:
            await self.__set_read_after_write(enable)

    async def __set_read_after_write(self, enable: bool) -> None:
        """
        This functions needs a lock on self.__conn.meta['lock'].
        """
        enable = bool(int(enable))
        await self.__write(f"++auto {enable:d}".encode("ascii"))
        self.__state.read_after_write = enable
        self.__conn.meta["read_after_write"] = enable

    async def get_read_after_write(self) -> bool:
        """
        Returns
        -------
        bool
            True if the instruments will be asked to TALK after each command.
        """
        async with self.__conn.meta["lock"]:
            return bool(int(await self.__query_command(b"++auto")))

    async def set_address(self, pad: int, sad: int = 0) -> None:
        """
        Change the current address of the GPIB controller. If set to device mode, this is the address the controller
        is listening to. If set to controller mode, it is the address of the device being to talked to.

        Parameters
        ----------
        pad: int
            Primary address in the range [0, 30]
        sad: int, default=0
            Secondary address in the range [96, 126]
        """
        async with self.__conn.meta["lock"]:
            await self.__set_address(pad, sad)

    async def __set_address(self, pad: int, sad: int = 0) -> None:
        """
        This function needs a lock on self.__conn.meta['lock'].
        """
        assert (0 <= pad <= 30) and (sad == 0 or (0x60 <= sad <= 0x7E))

        if sad == 0:
            address = f"++addr {pad:d}".encode("ascii")
        else:
            address = f"++addr {pad:d} {sad:d}".encode("ascii")

        await self.__write(address)
        self.__state.pad = pad
        self.__state.sad = sad
        self.__conn.meta["pad"] = pad
        self.__conn.meta["sad"] = sad

    async def get_address(self) -> dict[str, int]:
        """
        Returns
        -------
        dict
            The keys are 'pad' and 'sad' and their values are the primary and secondary address.
        """
        indices = ["pad", "sad"]
        async with self.__conn.meta["lock"]:
            addresses = await self.__query_command(b"++addr")

        # The result might be either "pad" or "pad sad"
        # The secondary address is offset by 0x60 (96).
        # See here for the reason:
        # http://www.ni.com/tutorial/2801/en/#:~:text=The%20secondary%20address%20is%20actually,the%20last%20bit%20is%20not
        # We return a dict looking like this {"pad": pad, "sad": 0} or {"pad": pad, "sad": sad}
        # So we first split the string, then create a list of ints
        result = [int(addr) for i, addr in enumerate(addresses.split(b" "))]
        result += [0] * (2 - len(result))  # pad with 0 up to a length of 2

        # Create the dict, zip_longest() pads the result list with 0 if needed
        return dict(zip(indices, result))

    async def set_eoi(self, enable: bool = True) -> None:
        """
        Enable or disable asserting the EOI (End of Identify) line after each transfer. Some older devices might not
        want or need the EOI line to be signaled after each command.

        Parameters
        ----------
        enable: bool
            Assert the eoi line after each transfer if True.
        """
        async with self.__conn.meta["lock"]:
            await self.__set_eoi(enable)

    async def __set_eoi(self, enable: bool) -> None:
        """
        This function needs a lock on self.__conn.meta['lock'].
        """
        enable = bool(int(enable))
        await self.__write(f"++eoi {enable:d}".encode("ascii"))
        self.__state.send_eoi = bool(int(enable))
        self.__conn.meta["send_eoi"] = bool(int(enable))

    async def get_eoi(self) -> bool:
        """
        Returns
        -------
        bool
            True if the EOI line is signaled after each transfer.
        """
        async with self.__conn.meta["lock"]:
            return bool(int(await self.__query_command(b"++eoi")))

    async def set_eos_mode(self, mode: EosMode) -> None:
        """
        Some older devices do not listen to the EOI, but instead for b"\r", b"\n" or b"\r\n". Enable this setting by
        choosing the appropriate EosMode enum. The GPIB controller will then automatically append the control character
        when sending the EOI signal.

        Parameters
        ----------
        mode: EosMode
            Append CR+LF, CR, LF, or nothing.
        """
        async with self.__conn.meta["lock"]:
            await self.__set_eos_mode(mode)

    async def __set_eos_mode(self, mode: EosMode) -> None:
        """
        This function needs a lock on self.__conn.meta['lock'].
        """
        assert isinstance(mode, EosMode)

        await self.__write(f"++eos {mode.value:d}".encode("ascii"))
        self.__state.eos_mode = mode
        self.__conn.meta["eos_mode"] = mode

    async def get_eos_mode(self) -> EosMode:
        """
        Returns
        -------
        EosMode
            The characters appended after each transfer.
        """
        async with self.__conn.meta["lock"]:
            return EosMode(int(await self.__query_command(b"++eos")))

    async def set_eot(self, enable: bool) -> None:
        """
        Enable this to append a character if an EOI is triggered. THe character will be appended to the data coming from
        the device. This is useful, if the device itself does not append a character, because the network protocol does
        not signal the EOI. Note: This feature is problematic when the transfer type is binary.

        Parameters
        ----------
        enable: bool
            Append a character to the data received on EOI if True.
        """
        async with self.__conn.meta["lock"]:
            await self.__set_eot(enable)

    async def __set_eot(self, enable: bool) -> None:
        """
        This function needs a lock on self.__conn.meta['lock'].
        """
        enable = bool(int(enable))

        await self.__write(f"++eot_enable {enable:d}".encode("ascii"))
        self.__state.send_eot = bool(int(enable))
        self.__conn.meta["send_eot"] = bool(int(enable))

    async def get_eot(self) -> bool:
        """
        Returns
        -------
        bool
            True if the controller appends a user specified character after receiving an EOI.
        """
        async with self.__conn.meta["lock"]:
            return bool(int(await self.__query_command(b"++eot_enable")))

    async def set_eot_char(self, character: bytes) -> None:
        """
        Append a character to the device output. Most GPIB devices only use 7-bit characters. So it is typically safe
        to use a character in the range of 0x80 to 0xFF.
        Note: It might not be safe for binary transmissions.

        Parameters
        ----------
        character: bytes
            Character to be appended
        """
        async with self.__conn.meta["lock"]:
            await self.__set_eot_char(character)

    async def __set_eot_char(self, character: bytes) -> None:
        """
        This function needs a lock on self.__conn.meta['lock'].
        """
        await self.__write(f"++eot_char {ord(character):d}".encode("ascii"))
        self.__state.eot_char = character
        self.__conn.meta["eot_char"] = character

    async def get_eot_char(self) -> str:
        """
        Returns
        -------
        str
            Character, which will be appended after receiving an EOI from the device.
        """
        async with self.__conn.meta["lock"]:
            return chr(int(await self.__query_command(b"++eot_char")))

    async def remote_enable(self, enable: bool = True) -> None:
        """
        Set the device to remote mode, typically disabling the front panel.

        Parameters
        ----------
        enable: bool
            If True, set remote enable.
        """
        async with self.__conn.meta["lock"]:
            await self.__ensure_state()
            if bool(enable):
                await self.__write(b"++llo")
            else:
                await self.__ibloc()

    def get_connection_timeout(self) -> float:
        """
        Returns
        -------
        float
            The GPIB timeout + the connection timeout. This is not the GPIB timeout as set by `timeout()`.
        """
        return self.__conn.timeout

    async def timeout(self, value: float) -> None:
        """
        Set the GPIB timeout for a read. This is not the network timeout, which comes on top of that.

        Parameters
        ----------
        value: float
            Timeout in seconds
        """
        async with self.__conn.meta["lock"]:
            await self.__timeout(value)

    async def __timeout(self, value: float):
        """
        This function needs a lock on self.__conn.meta['lock'].
        """
        value_ms = round(value * 1000)  # convert to ms
        assert value_ms >= 1  # Allow values greater than 3000 ms, because the wait() method can take arbitrary values

        await self.__write(f"++read_tmo_ms {min(value_ms,3000):d}".encode("ascii"))  # Cap value to 3000 max
        self.__state.timeout = value
        self.__conn.meta["timeout"] = value

    async def __ibloc(self) -> None:
        """
        This function needs a lock on self.__conn.meta['lock'].
        """
        await self.__write(b"++loc")

    async def ibloc(self) -> None:
        """
        Set the device to local mode, return control to the front panel.
        """
        async with self.__conn.meta["lock"]:
            await self.__ensure_state()
            await self.__ibloc()

    async def get_status(self) -> int:
        """
        Returns
        -------
        int
            status byte, that will be sent to a controller if serial polled by the controller.
        """
        async with self.__conn.meta["lock"]:
            await self.__ensure_state()
            return int(await self.__query_command(b"++status"))

    async def set_status(self, value: int) -> None:
        """
        Sets the status byte, that will be sent to a controller if serial polled by the
        controller.

        Parameters
        ----------
        value: int
            Value of the status byte
        """
        assert 0 <= value <= 255

        async with self.__conn.meta["lock"]:
            await self.__ensure_state()
            await self.__write(f"++status {value:d}".encode("ascii"))

    async def interface_clear(self) -> None:
        """
        Assert the Interface Clear (IFC) line and force the instrument to listen.
        """
        async with self.__conn.meta["lock"]:
            await self.__ensure_state()
            await self.__write(b"++ifc")

    async def clear(self) -> None:
        """
        Send the Selected Device Clear (SDC) event, which orders the device to clear its input and output buffer.
        """
        async with self.__conn.meta["lock"]:
            await self.__ensure_state()
            await self.__write(b"++clr")

    async def trigger(
        self, devices: tuple[int | tuple[int, int] | list[int], ...] | list[int | tuple[int, int] | list[int]] = ()
    ) -> None:
        """
        Trigger the selected instrument, or if specified a list of devices.
        The list of devices can either be a list (or tuple) of primary addresses or a list/tuple of lists/tuples of
        primary and secondary addresses.
        Mixing is allowed as well.
        Examples: devices=(22,10) will trigger pad 22 and 10
                  devices=((22,96),10) will trigger (pad 22, sad 96) and pad 10

        devices: tuple of int or tuple of tuples of int
            tuple of pads or tuple of (pad, sad) tuples
        """
        assert len(devices) <= 15

        async with self.__conn.meta["lock"]:
            # No need to call __ensure_state(), as we will trigger the device by its address
            if len(devices) == 0:
                command = b"++trg " + bytes(str(self.__state.pad), "ascii")
                if self.__state.sad != 0:
                    command += b" " + bytes(str(self.__state.sad), "ascii")
                await self.__write(command)
            else:
                command = b"++trg"
                for device in devices:
                    if isinstance(device, (list, tuple)):
                        pad, sad = device
                        assert (0 <= pad <= 30) and (sad == 0 or (0x60 <= sad <= 0x7E))
                        command += b" " + bytes(str(int(pad)), "ascii") + b" " + bytes(str(int(sad)), "ascii")
                    else:
                        assert 0 <= device <= 30
                        command += b" " + bytes(str(int(device)), "ascii")
                await self.__write(command)

    async def version(self) -> str:
        """
        Returns
        -------
        str
            Version string of the Prologix GPIB controller.
        """
        async with self.__conn.meta["lock"]:
            # Return a unicode string
            return (await self.__query_command(b"++ver")).decode()

    async def serial_poll(self, pad: int = 0, sad: int = 0) -> int:
        """
        Perform a serial poll of the instrument at the given address.
        If no address is given poll the current instrument.

        Parameters
        ----------
        pad: int
            primary address
        sad: int
            secondary address

        Returns
        -------
        int
            Status byte of the device
        """
        assert (0 <= pad <= 30) and (sad == 0 or (0x60 <= sad <= 0x7E))

        async with self.__conn.meta["lock"]:
            command = b"++spoll"
            if pad != 0:
                # if pad (and sad) are given, we do not need to enforce the current state
                command += b" " + bytes(str(int(pad)), "ascii")
                if sad != 0:
                    command += b" " + bytes(str(int(sad)), "ascii")
            else:
                await self.__ensure_state()

            return int(await self.__query_command(command))

    async def __wait(self) -> int:
        """
        The Prologix controller does not support callbacks, so this functions polls the controller
        until it finds the device has set the SRQ bit. Then returns the status byte

        Returns
        -------
        int
            The status byte
        """
        while True:
            # Note: The task will be garbage collected, if we exit the function
            sleep_task: asyncio.Task = asyncio.create_task(asyncio.sleep(self.__wait_delay))

            # Test if the SRQ line has been pulled low and if this was done by the instrument managed by this class.
            if await self.test_srq():
                spoll = await self.serial_poll(self.__state.pad, self.__state.sad)
                if spoll & (1 << 6):  # SRQ bit set
                    # Cancel the wait and return early
                    return spoll

            # Now wait until self.__wait_delay is over. Then start a new request.
            await sleep_task

    async def wait(self, mask: int) -> int:
        """
        Wait for an SRQ of the selected device. Wait at least self.__wait_delay before querying again, but return early,
        if the bit is set. The available mask flags are defined in RqsMask. It returns the status byte after waiting.

        Parameters
        ----------
        mask: int
            ibsta bits designating events to wait for.

        Returns
        -------
        int
            The status byte

        Raises
        ------
        ValueError
            If RqsMask.RQS is not set.
        asyncio.TimeoutError:
            If the connection timeout runs out before the device signals a request for service
        """
        rqs_mask = RqsMask(mask)
        if not bool(rqs_mask & RqsMask.RQS):
            raise ValueError("{RqsMask.RQS} not set")

        if bool(rqs_mask & RqsMask.TIMO):
            # Wait for the GPIB + connection timeout
            return await asyncio.wait_for(self.__wait(), timeout=self.__conn.timeout)

        return await self.__wait()

    async def test_srq(self) -> bool:
        """
        Check if the service request line is asserted. This can be used by the device to get the attention of the
        controller without constantly polling read().

        Returns
        -------
        bool
            True if the service request line is asserted.
        """
        async with self.__conn.meta["lock"]:  # The lock is needed for the query to make sure no one else is reading
            return bool(int(await self.__query_command(b"++srq")))

    async def reset(self) -> None:
        """
        Reset the controller. It takes about five seconds for the controller to reboot.
        """
        await self.__write(b"++rst")

    async def set_save_config(self, enable: bool = False) -> None:
        """
        Save the following configuration options to the controller EEPROM:
        DeviceMode, GPIB address, read-after-write, EOI, EOS, EOT, EOT character and the timeout
        Note: this will wear out the EEPROM if used very, very frequently. It is disabled by default.

        Parameters
        ----------
        enable: bool
            Save the configuration to the EEPROM on changes if True.
        """
        enable = bool(int(enable))
        await self.__write(f"++savecfg {enable:d}".encode("ascii"))

    async def get_save_config(self) -> bool:
        """
        Check if the following options are automatically saved to the EEPROM:
        DeviceMode, GPIB address, read-after-write, EOI, EOS, EOT, EOT character and the timeout

        Returns
        -------
        bool
            True if the config is automatically saved to the EEPROM.
        """
        async with self.__conn.meta["lock"]:  # The lock is needed for the query to make sure no one else is reading
            return bool(int(await self.__query_command(b"++savecfg")))

    async def set_listen_only(self, enable: bool) -> None:
        """
        Set the controller to listen-only mode. This will cause the controller to listen to all traffic,
        irrespective of the current address.

        Parameters
        ----------
        enable: bool
            Put the controller in listen-only mode if True.
        """
        await self.__write(f"++lon {enable:d}".encode("ascii"))

    async def get_listen_only(self) -> bool:
        """
        Returns
        -------
        bool
            True if the controller is in listen-only mode.
        """
        async with self.__conn.meta["lock"]:  # The lock is needed for the query to make sure no one else is reading
            return bool(int(await self.__query_command(b"++lon")))

    async def __set_device_mode(self, device_mode: DeviceMode) -> None:
        """
        Either configure the GPIB controller as a controller or device.

        Parameters
        ----------
        device_mode: DeviceMode
            device or controller mode
        """
        assert isinstance(device_mode, DeviceMode)

        await self.__write(f"++mode {device_mode.value:d}".encode("ascii"))
        self.__state.device_mode = device_mode
        self.__conn.meta["device_mode"] = device_mode

    def set_wait_delay(self, value: float) -> None:
        """
        Set the number of seconds to wait between serial polling the status byte, when waiting.

        Parameters
        ----------
        value: float
            time in seconds to wait between serial polling the status the device when waiting for state
            changes. Minimum value: 0.100 s, maximum value: the timeout set the GPIB device.

        See Also
        ----------
        wait : wait for an event
        """
        assert 0.1 <= value <= self.__state.timeout

        self.__wait_delay = min(max(value, 0.1), self.__state.timeout)
