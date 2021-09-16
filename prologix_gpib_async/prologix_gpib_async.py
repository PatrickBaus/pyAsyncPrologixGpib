# -*- coding: utf-8 -*-
"""
This module implements the API used by the Prologix GPIB adapters in pure python using AsyncIO.
The manual can be found here: http://prologix.biz/downloads/PrologixGpibEthernetManual.pdf
"""
import asyncio
from enum import Enum, Flag, unique
from itertools import zip_longest
import re   # needed to escape characters in the byte stream

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
    APPEND_CR    = 1
    APPEND_LF    = 2
    APPEND_NONE  = 3

@unique
class RqsMask(Flag):
    """
    The bitmask used, when serial polling a GPIB device to determine if the device requests service
    (RQS) or has a timeout (TIMO).
    """
    NONE = 0
    RQS  = (1 << 11)
    TIMO = (1 << 14)

# The following characters need to be escaped according to:
# http://prologix.biz/downloads/PrologixGpibEthernetManual.pdf
translation_map = {
    b'\r'  : b'\x1B\r',
    b'\n'  : b'\x1B\n',
    b'+'   : b'\x1B+',
    b'\x1B': b'\x1B\x1B',
}

# Generate a regex pattern which maches either of the characters (|).
# Characters like "\n" need to be escaped when used in a regex, so we run re.ecape on
# all characters first.
escape_pattern = re.compile(b'|'.join(map(re.escape, translation_map.keys())))

class AsyncPrologixGpib():  # pylint: disable=too-many-public-methods
    """
    The base class used by both the Prologix GPIB controller and GPIB device.
    """
    @property
    def _conn(self):
        return self.__conn

    def __init__(self, conn, pad, device_mode, sad, timeout, send_eoi, eos_mode, wait_delay):   # pylint: disable=too-many-arguments
        """
        Parameters
        ----------
        conn: AsyncSharedIPConnection
            a pooled ip conenction
        pad: int
            primary address
        device_mode: DeviceMode
            run the controller either as a device or a bus controller
        sad: int
            secondary address
        timeout: int
            timeout for operations in ms
        send_eoi: bool
            assert EOI on write
        eos_mode: bool:
            end-of-string termination
        wait_delay: int
            number of ms to wait in between serial polling a device when waiting
        """
        self.__conn = conn
        self.__state = {
          'pad'             : pad,
          'sad'             : sad,
          'send_eoi'        : bool(int(send_eoi)),
          'send_eot'        : False,
          'eot_char'        : b'\n',
          'eos_mode'        : EosMode(eos_mode),
          'timeout'         : timeout,
          'read_after_write': False,
          'device_mode'     : device_mode,
        }
        self.set_wait_delay(wait_delay)

    async def connect(self):
        """
        Connect to the ethernet controller and configure the device as a GPIB controller. By default the configuration
        will not be saved to EEPROM to safe write cycles.
        """
        try:
            await self.__conn.connect()
            lock = self.__conn.meta.setdefault('lock', asyncio.Lock())  # either create a new lock or get the old one
            async with lock:
                await asyncio.gather(
                    self.set_save_config(False),    # Disable saving the config to EEPROM by default to save EEPROM writes
                    self.__ensure_state(),
                )
        except BaseException:   # pylint: disable=broad-except
            await self.__conn.disconnect()

    async def close(self):
        """
        This is an alias for disconnect().
        """
        await self.disconnect()

    async def disconnect(self):
        """
        Close the ip connection and flush its buffers.
        """
        await self.__conn.disconnect()

    async def __ensure_state(self):
        """
        Push the current state of the gpib device to the remote state of the controller.
        Note: Before calling this function, acquire the self.__conn.meta['lock'], to ensure, that only one gpib device
        is modifying the remote state of the controller.
        """
        jobs = []
        if self.__state['device_mode'] != self.__conn.meta.get('device_mode'):
            jobs.append(self.__set_device_mode(self.__state['device_mode']))
        if self.__state['pad'] != self.__conn.meta.get('pad') or self.__state['sad'] != self.__conn.meta.get('sad'):
            jobs.append(self.__set_address(self.__state['pad'], self.__state['sad']))
        if self.__state['read_after_write'] != self.__conn.meta.get('read_after_write'):
            jobs.append(self.__set_read_after_write(self.__state['read_after_write']))
        if self.__state['send_eoi'] != self.__conn.meta.get('send_eoi'):
            jobs.append(self.__set_eoi(self.__state['send_eoi']))
        if self.__state['send_eot'] != self.__conn.meta.get('send_eot'):
            jobs.append(self.__set_eot(self.__state['send_eot']))
        if self.__state['eot_char'] != self.__conn.meta.get('eot_char'):
            jobs.append(self.__set_eot_char(self.__state['eot_char']))
        if self.__state['eos_mode'] != self.__conn.meta.get('eos_mode'):
            jobs.append(self.__set_eos_mode(self.__state['eos_mode']))
        if self.__state['timeout'] != self.__conn.meta.get('timeout'):
            jobs.append(self.__timeout(self.__state['timeout']))

        if jobs:
            await asyncio.gather(*jobs)

    async def __query_command(self, command):
        """
        Issue a Prologix command and return the result. This function will strip the \r\n control sequence returned
        by the controller.
        Note: Before calling this function, acquire the self.__conn.meta['lock'], to ensure, that only one read
        request is performed.

        Parameters
        ----------
        command: bytes
            sequence of bytes to write

        Returns
        -------
        bytes
            sequence of bytes which was read
        """
        await self.__write(command)
        return (await self.__conn.read(eol_character=b'\n'))[:-2]    # strip the EOT characters ("\r\n")

    @staticmethod
    def __escape_data(data):
        """
        The prologix adapter uses ++ to signal commands. The \r\n characters are used to separate messages. In order to
        transmit these characters to the GPIB device, they need to be escaped using the ESC character (\x1B). Therefore
        \r, \n, \x1B (27, ESC) and "+" need to be escaped.

        Parameters
        ----------
        data: bytes
            sequence of bytes to escape

        Returns
        -------
        bytes
            sequence of escaped bytes
        """
        # Use a regex to match them, then replace them using a translation map
        return escape_pattern.sub(lambda match: translation_map[match.group(0)], data)

    async def __write(self, data):
        await self.__conn.write(data + b'\n')   # Append Prologix termination character

    async def write(self, data):
        """
        Send a byte string to the GPIB device. The byte string will automatically be escaped, so it is not possible to
        send commands to the GPIB controller.

        Parameters
        ----------
        data: bytes
            sequence of bytes to write
        """
        data = self.__escape_data(data)
        async with self.__conn.meta['lock']:
            await self.__ensure_state()
            await self.__write(data)

    async def read(self, length=None, character=None, force_poll=True):
        """
        Read data until an EOI (End of Identify) was received (default), or if the character parameter is set until the
        character is received. Using the len parameter it is possible to read only a certain number of bytes.
        The underlying network protocol is a stream protocol, which does not know about the EOI of the GPIB bus. By
        default a packet is terminated by a \n. If the device does not terminate its packets with either \r\n or \n,
        consider using an EOT characer, if there is no way of knowing the number of bytes returned.
        When using the "read after write" feature, set force_poll to False, when querying.

        Parameters
        ----------
        length: int, default=None
            number of bytes to read.
        character: byte
            an eol characer

        Returns
        -------
        bytes
            sequence of bytes
        """
        async with self.__conn.meta['lock']:
            await self.__ensure_state()
            if force_poll or not self.__state['read_after_write']:
                if character is None:
                    await self.__write(b'++read eoi')
                else:
                    await self.__write(f"++read {ord(character):d}".encode('ascii'))

            return await self.__conn.read(length=length, eol_character=self.__state['eot_char'] if self.__state['send_eot'] else None)

    async def get_device_mode(self):
        """
        Returns
        -------
        DeviceMode
            configuration of the GPIB adapter
        """
        async with self.__conn.meta['lock']:
            return DeviceMode(int(await self.__query_command(b'++mode')))

    async def set_read_after_write(self, enable):
        """
        If enabled automatically triggers the instrument to TALK after each command. If set, the instrument is also
        immediately asked to TALK (enable==True) or LISTEN (enable==False).

        Parameters
        ----------
        enable: bool
            ask the device to talk after each command if True
        """
        async with self.__conn.meta['lock']:
            await self.__set_read_after_write(enable)

    async def __set_read_after_write(self, enable):
        """
        This functios needs a lock on self.__conn.meta['lock'].
        """
        enable = bool(int(enable))
        await self.__write(f"++auto {enable:d}".encode('ascii'))
        self.__state['read_after_write'] = enable
        self.__conn.meta['read_after_write'] = enable

    async def get_read_after_write(self):
        """
        Returns
        -------
        bool
            True if the instruments will be asked to TALK after each command.
        """
        async with self.__conn.meta['lock']:
            return bool(int(await self.__query_command(b'++auto')))

    async def set_address(self, pad, sad=0):
        """
        Change the current address of the GPIB controller. If set to device mode, this is the address the controller
        is listening to. If set to controller mode, it is the address of the device being to talked to.

        Parameters
        ----------
        pad: int
            primary address in the range [0, 30]
        sad: int, default=0
            secondary adddress in the range [96, 126]
        """
        async with self.__conn.meta['lock']:
            await self.__set_address(pad, sad)

    async def __set_address(self, pad, sad=0):
        """
        This functios needs a lock on self.__conn.meta['lock'].
        """
        assert (0 <= pad <= 30) and (sad == 0 or (0x60 <= sad <= 0x7E))

        if sad == 0:
            address = f"++addr {pad:d}".encode('ascii')
        else:
            address = f"++addr {pad:d} {sad:d}".encode('ascii')

        await self.__write(address)
        self.__state['pad'] = pad
        self.__state['sad'] = sad
        self.__conn.meta['pad'] = pad
        self.__conn.meta['sad'] = sad

    async def get_address(self):
        """
        Returns
        -------
        dict
            The keys are 'pad' and 'sad' and the their values are the primary and secondary address
        """
        indices = ["pad", "sad"]
        async with self.__conn.meta['lock']:
            result = await self.__query_command(b'++addr')

        # The result might by either "pad" or "pad sad"
        # The secondary address is offset by 0x60 (96).
        # See here for the reason: http://www.ni.com/tutorial/2801/en/#:~:text=The%20secondary%20address%20is%20actually,the%20last%20bit%20is%20not
        # We return a dict looking like this {"pad": pad, "sad": 0} or {"pad": pad, "sad": sad}
        # So we first split the string, then create a list of ints
        result = [int(addr) for i, addr in enumerate(result.split(b' '))]

        # Create the dict, zip_longest() pads the result list with 0 if needed
        return dict(zip_longest(indices, result, fillvalue=0))

    async def set_eoi(self, enable=True):
        """
        Enable or disable asserting the EOI (End of Identify) line after each transfer. Some older devices might not want
        or need the EOI line to be signaled after each command.

        Parameters
        ----------
        enable: bool
            assert the eoi line after each transfer if True
        """
        async with self.__conn.meta['lock']:
            await self.__set_eoi(enable)

    async def __set_eoi(self, enable):
        """
        This functios needs a lock on self.__conn.meta['lock'].
        """
        enable = bool(int(enable))
        await self.__write(f"++eoi {enable:d}".encode('ascii'))
        self.__state['send_eoi'] = bool(int(enable))
        self.__conn.meta['send_eoi'] = bool(int(enable))

    async def get_eoi(self):
        """
        Returns
        -------
        bool
            True if the EOI line is signaled after each transfer.
        """
        async with self.__conn.meta['lock']:
            return bool(int(await self.__query_command(b'++eoi')))

    async def set_eos_mode(self, mode):
        """
        Some older devices do not listen to the EOI, but instead for \r, \n or \r\n. Enable this setting by choosing
        the appropriate EosMode enum. The GPIB controller will then automatically append the control character when
        sending the EOI signal.

        Parameters
        ----------
        mode: EosMode
            append CR+LF, CR, LF, or nothing
        """
        async with self.__conn.meta['lock']:
            await self.__set_eos_mode(mode)

    async def __set_eos_mode(self, mode):
        """
        This functios needs a lock on self.__conn.meta['lock'].
        """
        assert isinstance(mode, EosMode)

        await self.__write(f"++eos {mode.value:d}".encode('ascii'))
        self.__state['eos_mode'] = mode
        self.__conn.meta['eos_mode'] = mode

    async def get_eos_mode(self):
        """
        Returns
        -------
        EosMode
            the characers appended after each transfer
        """
        async with self.__conn.meta['lock']:
            return EosMode(int(await self.__query_command(b'++eos')))

    async def set_eot(self, enable):
        """
        Enable this to append a character if an EOI is triggered. THe character will be appended to the data coming from
        the device. This is useful, if the device itself does not append a character, because the network protocol does
        not signal the EOI. Note: This feature is problematic when the transfer type is binary.

        Parameters
        ----------
        enable: bool
            append a character to the data received on EOI if True
        """
        async with self.__conn.meta['lock']:
            await self.__set_eot(enable)

    async def __set_eot(self, enable):
        """
        This functios needs a lock on self.__conn.meta['lock'].
        """
        enable = bool(int(enable))

        await self.__write(f"++eot_enable {enable:d}".encode('ascii'))
        self.__state['send_eot'] = bool(int(enable))
        self.__conn.meta['send_eot'] = bool(int(enable))

    async def get_eot(self):
        """
        Returns
        -------
        bool
            True if the controller appends a user specified character after receiving an EOI.
        """
        async with self.__conn.meta['lock']:
            return bool(int(await self.__query_command(b'++eot_enable')))

    async def set_eot_char(self, character):
        """
        Append a character to the device output. Most GPIB devices only use 7-bit characters. So it is typically safe
        to use a character in the range of 0x80 to 0xFF.
        Note: It might not be safe for binary transmissions.

        Parameters
        ----------
        character: byte
            characer to be appended
        """
        async with self.__conn.meta['lock']:
            await self.__set_eot_char(character)

    async def __set_eot_char(self, character):
        """
        This functios needs a lock on self.__conn.meta['lock'].
        """
        await self.__write(f"++eot_char {ord(character):d}".encode('ascii'))
        self.__state['eot_char'] = character
        self.__conn.meta['eot_char'] = character

    async def get_eot_char(self):
        """
        Returns
        -------
        byte
            character, which will be appended after receiving an EOI from the device.
        """
        async with self.__conn.meta['lock']:
            return chr(int(await self.__query_command(b'++eot_char')))

    async def remote_enable(self, enable=True):
        """
        Set the device to remote mode, typically disabling the front panel.

        Parameters
        ----------
        enable: bool
            if True, set remote enable
        """
        async with self.__conn.meta['lock']:
            await self.__ensure_state()
            if bool(enable):
                await self.__write(b'++llo')
            else:
                await self.__ibloc()

    async def timeout(self, value):
        """
        Set the GPIB timeout for a read. This is not the network timeout, which comes on top of that.

        Parameters
        ----------
        value: int
            timeout in ms
        """
        async with self.__conn.meta['lock']:
            await self.__timeout(value)

    async def __timeout(self, value):
        """
        This functios needs a lock on self.__conn.meta['lock'].
        """
        assert value >= 1   # Allow values greater than 3000 ms, because the wait() method can take arbitrary values

        await self.__write(f"++read_tmo_ms {min(value,3000):d}".encode('ascii')) # Cap value to 3000 max
        self.__state['timeout'] = value
        self.__conn.meta['timeout'] = value

    async def __ibloc(self):
        """
        This functios needs a lock on self.__conn.meta['lock'].
        """
        await self.__write(b'++loc')

    async def ibloc(self):
        """
        Set the device to local mode, return control to the front panel.
        """
        async with self.__conn.meta['lock']:
            await self.__ensure_state()
            await self.__ibloc()

    async def get_status(self):
        """
        Returns
        -------
        int
            status byte, that will be sent to a controller if serial polled by the controller.
        """
        async with self.__conn.meta['lock']:
            await self.__ensure_state()
            return int(await self.__query_command(b'++status'))

    async def set_status(self, value):
        """
        Sets the status byte, that will be sent to a controller if serial polled by the
        controller.

        Parameters
        ----------
        value: int
            value of the status byte
        """
        assert 0 <= value <= 255

        async with self.__conn.meta['lock']:
            await self.__ensure_state()
            await self.__write(f"++status {value:d}".encode('ascii'))

    async def interface_clear(self):
        """
        Assert the Interface Clear (IFC) line and force the instrument to listen.
        """
        async with self.__conn.meta['lock']:
            await self.__ensure_state()
            await self.__write(b'++ifc')

    async def clear(self):
        """
        Send the Selected Device Clear (SDC) event, which orders the device to clear its input and output buffer.
        """
        async with self.__conn.meta['lock']:
            await self.__ensure_state()
            await self.__write(b'++clr')

    async def trigger(self, devices=()):
        """
        Trigger the selected instrument, or if specified a list of devices.
        The list of devices can either be a list (or tuple) of pads or a list/tuple of lists/tuples of pads and sads.
        Mixing is allowed as well.
        Examples: devices=(22,10) will trigger pad 22 and 10
                  devices=((22,96),10) will trigger (pad 22, sad 96) and pad 10

        devices: tuple of int or tuple of tuple of int
            tuple of pads or tuple of (pad, sad) tuples
        """
        assert len(devices) <= 15

        if len(devices) == 0:
            async with self.__conn.meta['lock']:
                # No need to call __ensure_state(), as we will trigger the device by its address
                command = b'++trg ' + bytes(str(self.__state['pad']), 'ascii')
                if self.__state['sad'] != 0:
                    command += b' ' + bytes(str(self.__state['sad']), 'ascii')
                await self.__write(command)
        else:
            command = b'++trg'
            for device in devices:
                if isinstance(device, (list, tuple)):
                    pad, sad = device
                    assert (0<= pad <=30) and (sad==0 or (0x60 <= sad <= 0x7E))
                    command += b' ' + bytes(str(int(pad)), 'ascii') + b' ' + bytes(str(int(sad)), 'ascii')
                else:
                    assert 0 <= device <= 30
                    command += b' ' + bytes(str(int(device)), 'ascii')
            await self.__write(command)

    async def version(self):
        """
        Returns
        -------
        str
            version string of the Prologix GPIB controller.
        """
        async with self.__conn.meta['lock']:
            # Return a unicode string
            return (await self.__query_command(b'++ver')).decode()

    async def serial_poll(self, pad=0, sad=0):
        """
        Perform a serial poll of the instrument at the given address. If no address is given poll the current instrument.

        Parameters
        ----------
        pad: int
            primary address
        sad: int
            secondary address

        Returns
        -------
        int
            status byte of the device
        """
        assert (0 <= pad <= 30) and (sad==0 or (0x60 <= sad <= 0x7E))

        command = b'++spoll'
        if pad != 0:
            # if pad (and sad) are given, we do not need to enforce the current state
            command += b' ' + bytes(str(int(pad)), 'ascii')
            if sad != 0:
                command += b' ' + bytes(str(int(sad)), 'ascii')
            async with self.__conn.meta['lock']:
                return int(await self.__query_command(command))
        else:
            async with self.__conn.meta['lock']:
                await self.__ensure_state()
                return int(await self.__query_command(command))

    async def __wait(self):
        """
        The Prologix controller does not support callbacks, so this functions polls the controller
        until it finds the device has set the SRQ bit.
        """
        while "waiting":
            sleep_task = asyncio.create_task(asyncio.sleep(self.__wait_delay/1000))

            # Test if the SRQ line has been pulled low. Then test if this was done by the instrument managed by this class.
            if await self.test_srq():
                spoll = await self.serial_poll(self.__state['pad'], self.__state['sad'])
                if spoll & (1 << 6):    # SRQ bit set
                    # Cancel the wait and return early
                    sleep_task.cancel()
                    return

            # Now wait until self.__wait_delay is over. Then start a new request.
            await sleep_task

    async def wait(self, mask):
        """
        Wait for an SRQ of the selected device. Wait at least self.__wait_delay before querying again, but return early, if the
        bit is set. The available mask flags are defined in RqsMask.

        Parameters
        ----------
        mask: int
            ibsta bits designating events to wait for
        """
        mask = RqsMask(mask)
        if not bool(mask & RqsMask.RQS):
            return

        if bool(mask & RqsMask.TIMO):
            await asyncio.wait_for(self.__wait(), timeout=self.__state['timeout']/1000)
        else:
            await self.__wait()

    async def test_srq(self):
        """
        Check if the service request line is asserted. This can be used by the device to get the attention of the
        controller without constantly polling read().

        Returns
        -------
        bool
            True if the service request line is asserted
        """
        return bool(int(await self.__query_command(b'++srq')))

    async def reset(self):
        """
        Reset the controller. It takes about five seconds for the controller to reboot.
        """
        await self.__write(b'++rst')

    async def set_save_config(self, enable=False):
        """
        Save the the following configuration options to the controller EEPROM:
        DeviceMode, GPIB address, read-after-write, EOI, EOS, EOT, EOT character and the timeout
        Note: this will wear out the EEPROM if used very, very frequently. It is disabled by default.

        Parameters
        ----------
        enable: bool
            save the config to the EEPROM on changes if True
        """
        enable = bool(int(enable))
        await self.__write(f"++savecfg {enable:d}".encode('ascii'))

    async def get_save_config(self):
        """
        Check if the following options are automatically saved to the EEPROM:
        DeviceMode, GPIB address, read-after-write, EOI, EOS, EOT, EOT character and the timeout

        Returns
        -------
        bool
            True if the config is automatically saved to the EEPROM
        """
        return bool(int(await self.__query_command(b'++savecfg')))

    async def set_listen_only(self, enable):
        """
        Set the controller to liste-only mode. This will cause the controller to listen to all traffic,
        irrespective of the current address.

        Parameters
        ----------
        enable: bool
            put the controller in listen-only mode if True
        """
        await self.__write(f"++lon {enable:d}".encode('ascii'))

    async def get_listen_only(self):
        """
        Returns
        -------
        bool
            True if the controller is in listen-only mode.
        """
        return bool(int(await self.__query_command(b'++lon')))

    async def __set_device_mode(self, device_mode):
        """
        Either configure the GPIB controller as a controller or device.

        Parameters
        ----------
        device_mode: DeviceMode
            device or controller mode
        """
        assert isinstance(device_mode, DeviceMode)

        await self.__write(f"++mode {device_mode.value:d}".encode('ascii'))
        self.__state['device_mode'] = device_mode
        self.__conn.meta['device_mode'] = device_mode

    def set_wait_delay(self, value):
        """
        Set the number of ms to wait between serial polling the status byte, when waiting.

        Parameters
        ----------
        value: int
            time in ms to wait between serial polling the satatus the device when waiting for state
            changes. Minimum value: 100 ms, maximum value: the timeout set the GPIB device.

        See Also
        ----------
        wait : wait for an event
        """
        assert 100 <= value <= self.__state['timeout']

        self.__wait_delay = min(max(value, 100), self.__state['timeout'])

class AsyncPrologixGpibEthernetController(AsyncPrologixGpib):
    """
    Acts as the GPIB bus controller.
    """
    def __init__(self, hostname, pad, port=1234, sad=0, timeout=3000, send_eoi=True, eos_mode=EosMode.APPEND_NONE, ethernet_timeout=1000, wait_delay=250):   # timeout is in ms, pylint: disable=too-many-arguments
        conn = AsyncSharedIPConnection(hostname=hostname, port=port, timeout=(timeout+ethernet_timeout)/1000)   # timeout is in seconds
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

    async def set_listen_only(self, enable):
        raise TypeError("Not supported in controller mode")

    async def get_listen_only(self):
        raise TypeError("Not supported in controller mode")

    async def set_status(self, value):
        raise TypeError("Not supported in controller mode")

    async def get_status(self):
        raise TypeError("Not supported in controller mode")


class AsyncPrologixGpibEthernetDevice(AsyncPrologixGpib):
    """
    Acts as the a GPIB device on the bus.
    """
    def __init__(self, hostname, pad, port=1234, sad=0, send_eoi=True, eos_mode=EosMode.APPEND_NONE, ethernet_timeout=1000, wait_delay=250):   # timeout is in ms, pylint: disable=too-many-arguments
        conn = AsyncSharedIPConnection(hostname=hostname, port=port, timeout=ethernet_timeout/1000)   # timeout is in seconds
        super().__init__(
          conn=conn,
          pad=pad,
          sad=sad,
          device_mode=DeviceMode.DEVICE,
          timeout=None,
          send_eoi=send_eoi,
          eos_mode=eos_mode,
          wait_delay=wait_delay,
        )

    async def set_read_after_write(self, enable):
        raise TypeError("Not supported in device mode")

    async def get_read_after_write(self):
        raise TypeError("Not supported in device mode")

    async def clear(self):
        raise TypeError("Not supported in device mode")

    async def interface_clear(self):
        raise TypeError("Not supported in device mode")

    async def remote_enable(self, enable=True):
        raise TypeError("Not supported in device mode")

    async def ibloc(self):
        raise TypeError("Not supported in device mode")

    async def read(self, length=None, character=None, force_poll=True):
        raise TypeError("Not supported in device mode")

    async def timeout(self, value):
        raise TypeError("Not supported in device mode")

    async def serial_poll(self, pad=0, sad=0):
        raise TypeError("Not supported in device mode")

    async def test_srq(self):
        raise TypeError("Not supported in device mode")

    async def trigger(self, devices=()):
        raise TypeError("Not supported in device mode")

    async def wait(self, mask):
        raise TypeError("Not supported in device mode")

    def set_wait_delay(self, value):
        raise TypeError("Not supported in device mode")
