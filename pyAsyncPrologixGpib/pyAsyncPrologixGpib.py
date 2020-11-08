# -*- coding: utf-8 -*-
# ##### BEGIN GPL LICENSE BLOCK #####
#
# Copyright (C) 2020  Patrick Baus
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# ##### END GPL LICENSE BLOCK #####

import asyncio
from enum import Enum, unique
from itertools import zip_longest
import logging
import re   # needed to escape characters in the byte stream

from .ip_connection import AsyncIPConnection

@unique
class DeviceMode(Enum):
    DEVICE = 0
    CONTROLLER = 1

@unique
class EosMode(Enum):
    APPEND_CR_LF = 0
    APPEND_CR    = 1
    APPEND_LF    = 2
    APPEND_NONE  = 3

# The following characters need to be escaped according to:
# http://prologix.biz/downloads/PrologixGpibEthernetManual.pdf
translation_map = {
    b"\r"  : b"\x1B\r",
    b"\n"  : b"\x1B\n",
    b"+"   : b"\x1B+",
    b"\x1B": b"\x1B\x1B",
}

# Generate a regex pattern which, wich maches on either of the characters (|).
# Characters like "\n" need to be escaped when used in a regex, so we run re.ecape on
# all characters first.
escape_pattern = re.compile(b"|".join(map(re.escape, translation_map.keys())))

class EthernetProtocol()

class AsyncPrologixEthernet(EthernetProtocol):
    """
    name: Either e.g. "gpib0" (string) or 0 (integer)
    pad: primary address
    """
    def __init__(self, hostname, port=1234, timeout=1000, loop=None):
        self.__loop = asyncio.get_event_loop() if loop is None else loop
        self.__hostname = hostname
        self.__port = port

        self.__conn = AsyncIPConnection(timeout=timeout/1000, loop=self.__loop)   # timeout is in seconds
        self.__logger = logging.getLogger(__name__)

    @property
    def is_connected(self):
        return self.__conn.is_connected

    async def connect(self):
        await self.__conn.connect(self.__hostname, self.__port)

    async def close(self):
        await self.disconnect()

    async def disconnect(self):
        await self.__conn.disconnect()

    async def write(self, data):
        await self.__conn.write(data + b"\n")   # Append Prologix ETHERNET termination character

    async def read(self, length=None):
        data = await self.__conn.read(length=length)
        if length is None and len(data) >= 2:
            data = data[:-2]    # strip \r\n
        return data

class AsyncPrologixGpibEthernetController(AsyncPrologixEthernet):
    def __init__(self, hostname, pad, port=1234, sad=None, timeout=13, send_eoi=1, eos_mode=0, ethernet_timeout=1000, loop=None):
        super().__init__(hostname, port, timeout+ethernet_timeout, loop)
        self.__timeout = timeout

        self.__pad = pad
        self.__sad = sad
        self.__send_eoi = bool(send_eoi)
        self.__eos_mode = EosMode(eos_mode)

        self.__logger = logging.getLogger(__name__)

    async def connect(self):
        await super().connect()
        #TODO: await this
        await asyncio.gather(
            self.set_save_config(False),    # Disable saving the config to EEPROM by default, so save EEPROM writes
            self.set_device_mode(DeviceMode.CONTROLLER),
            self.set_read_after_write(False),
            self.set_eoi(self.__send_eoi),
            self.set_address(self.__pad, self.__sad),
            self.set_eos_mode(self.__eos_mode),
            self.timeout(self.__timeout)
        )

    def __escape_data(self, data):
        # \r, \n, \x1B (27, ESC), + need to be escaped
        # Use a regex to match them replace them using a translation map
        return escape_pattern.sub(lambda match: translation_map[match.group(0)], data)

    async def write(self, data):
        data = self.__escape_data(data)
        await super().write(data)

    async def read(self, len=None):
        await super().write(b"++read eoi")
        return await super().read(length=len)

    async def set_device_mode(self, device_mode):
        await super().write("++mode {value:d}".format(value=device_mode.value).encode('ascii'))

    async def get_device_mode(self):
        await super().write(b"++mode")
        return DeviceMode(int(await super().read()))

    async def set_read_after_write(self, enable):
        await super().write("++auto {value:d}".format(value=enable).encode('ascii'))

    async def get_read_after_write(self):
        await super().write(b"++auto")
        return bool(int(await super().read()))

    async def set_address(self, pad, sad=None):
        if sad is None:
          address = "++addr {pad:d}".format(pad=pad).encode('ascii')
        else:
          address = "++addr {pad:d} {sad:d}".format(pad=pad, sad=sad+96).encode('ascii')

        await super().write(address)

    async def get_address(self):
        indices = ["pad", "sad"]
        
        await super().write(b"++addr")
        # The result might by either "pad" or "pad sad"
        # The secondary address is offset by 96.
        # See here for the reason: http://www.ni.com/tutorial/2801/en/#:~:text=The%20secondary%20address%20is%20actually,the%20last%20bit%20is%20not
        # We return a dict looking like this {"pad": pad, "sad": None} or {"pad": pad, "sad": sad-96}
        # So we first split the string, then create a list of ints, and substract 96 from the second item (index = 1)
        result = [int(addr)-96*i for i, addr in enumerate((await super().read()).split(b" "))]

        # Create the dict, zip_longest pads the shorted list with None
        return dict(zip_longest(indices, result))

    async def set_eoi(self, enable):
        await super().write(b"++eoi " + bytes(str(int(enable)), 'ascii'))

    async def get_eoi(self):
        await super().write(b"++eoi")
        return bool(int(await super().read()))

    async def set_eos_mode(self, mode):
        await super().write("++eos {value:d}".format(value=mode.value).encode('ascii'))

    async def get_eos_mode(self):
        await super().write(b"++eos")
        return EosMode(int(await super().read()))

    async def set_eot(self, enable):
        await super().write("++eot_enable {value:d}".format(value=enable).encode('ascii'))

    async def get_eot(self):
        await super().write(b"++eot_enable")
        return bool(int(await super().read()))

    async def set_eot_char(self, character):
        await super().write("++eot_char {value:d}".format(value=ord(character)).encode('ascii'))

    async def get_eot_char(self):
        await super().write(b"++eot_char")
        return chr(int(await super().read()))

    async def remote_enable(self, enable=True):
        if bool(enable):
          await super().write(b"++llo")

    async def timeout(self, value):
        assert (1 <= value <= 3000)
        await super().write("++read_tmo_ms {value:d}".format(value=value).encode('ascii'))

    async def ibloc(self):
        await super().write(b"++loc")

    async def ibsta(self):
        await super().write(b"++status")
        return await super().read()

    async def interface_clear(self):
        await super().write(b"++ifc")

    async def clear(self):
        await super().write(b"++clr")

    async def trigger(self):
        await super().write(b"++trg")

    async def version(self):
        await super().write(b"++ver")
        # Return a unicode string
        return (await super().read()).decode()

    async def set_listen_only(self, enable):
        await super().write("++lon {value:d}".format(value=enable).encode('ascii'))

    async def get_listen_only(self):
        await super().write(b"++lon")
        return bool(int(await super().read()))

    async def serial_poll(self, pad=None, sad=None):
        command = b"++spoll"
        if pad is not None:
            command += b" " + bytes(str(int(pad)), 'ascii')
            if sad is not None:
                command += b" " + bytes(str(int(sad + 96)), 'ascii')
        await super().write(command)

        return await super().read()

    async def test_srq(self):
        await super().write(b"++srq")
        return bool(int(await super().read()))

    async def reset(self):
        await super().write(b"++rst")

    async def set_save_config(self, enable):
        await super().write("++savecfg {value:d}".format(value=enable).encode('ascii'))

    async def get_save_config(self):
        await super().write(b"++savecfg")
        return bool(int(await super().read()))
