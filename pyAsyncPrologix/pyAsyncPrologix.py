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
from enum import IntEnum, unique
from itertools import zip_longest
import logging
import re   # needed to escape characters in the byte stream

from .ip_connection import AsyncIPConnection

@unique
class DeviceMode(IntEnum):
    device = 0
    controller = 1

@unique
class EosMode(IntEnum):
    appendCrLf = 0
    appendCr   = 1
    appendLf   = 2
    appendNone = 3

# The following characters need to be escaped according to:
# http://prologix.biz/downloads/PrologixGpibEthernetManual.pdf
translation_map = {
    b"\r"  : b"\x1B\r",
    b"\n"  : b"\x1B\n",
    b"+"   : b"\x1B+",
    b"\x1B": b"\x1B\x1B",
}
inverse_translation_map = {v: k for k, v in translation_map.items()}

# Generate a regex pattern which, wich maches on either of the characters (|).
# Characters like "\n" need to be escaped when used in a regex, so we run re.ecape on
# all characters first.
escape_pattern = re.compile(b"|".join(map(re.escape, translation_map.keys())))
unescape_pattern = re.compile(b"|".join(map(re.escape, inverse_translation_map.keys())))

class AsyncPrologixEthernet():
    """
    name: Either e.g. "gpib0" (string) or 0 (integer)
    pad: primary address
    """
    def __init__(self, hostname, port=1234, loop=None):
        self.__loop = asyncio.get_event_loop() if loop is None else loop
        self.__hostname = hostname
        self.__port = port

        self.__conn = AsyncIPConnection(self.__loop)
        self.__logger = logging.getLogger(__name__)

    async def connect(self):
        await self.__conn.connect(self.__hostname, self.__port)

    async def close(self):
        await self.disconnect()

    async def disconnect(self):
        await self.__conn.disconnect()

    def write(self, data):
        self.__conn.write(data + b"\n")

    def __unescape_data(self, data):
        # Remove all b"\x1B" escape characters, but remember to keep one \x1B if it is escaped
        return unescape_pattern.sub(lambda match: inverse_translation_map[match.group(0)], data)

    async def read(self, len=512):
        data = (await self.__conn.read())[:-2]    # strip \r\n

        data = self.__unescape_data(data)
        return data

class AsyncPrologixGpibEthernetController(AsyncPrologixEthernet):
    def __init__(self, hostname, pad, port=1234, sad=None, timeout=13, send_eoi=1, eos_mode=0, loop=None):
        super().__init__(hostname, port, loop)
        self.__timeout = timeout

        self.__pad = pad
        self.__sad = sad
        self.__send_eoi = bool(send_eoi)
        self.__eos_mode = EosMode(eos_mode)

        self.__logger = logging.getLogger(__name__)

    async def connect(self):
        await super().connect()
        self.set_device_mode(DeviceMode.controller)
        self.set_read_after_write(False)
        self.set_eoi(self.__send_eoi)
        self.set_address(self.__pad, self.__sad)
        self.set_eos_mode(self.__eos_mode)

    def __escape_data(self, data):
        # \r, \n, \x1B (27, ESC), + need to be escaped
        # Use a regex to match them replace them using a translation map
        return escape_pattern.sub(lambda match: translation_map[match.group(0)], data)

    def write(self, data):
        data = self.__escape_data(data)
        super().write(data)

    async def read(self, len=512):
        super().write(b"++read eoi")
        return await super().read()

    def set_device_mode(self, device_mode):
        #self.__logger.debug("Setting device mode to: %(mode)s", {'mode': device_mode})
        super().write(b"++mode " + bytes(str(int(device_mode)), 'ascii'))

    async def get_device_mode(self):
        super().write(b"++mode")
        return DeviceMode(int(await super().read()))

    def set_read_after_write(self, enabled):
        super().write(b"++auto " + bytes(str(int(enabled)), 'ascii'))

    async def get_read_after_write(self):
        super().write(b"++auto")
        return bool(int(await super().read()))

    def set_address(self, pad, sad=None):
        address = b"++addr " + bytes(str(int(pad)), 'ascii')
        if sad is not None:
          address += b" " + bytes(str(int(sad + 96)), 'ascii')

        super().write(address)

    async def get_address(self):
        indices = ["pad", "sad"]
        
        super().write(b"++addr")
        # The result might by either "pad" or "pad sad"
        # The secondary address is offset by 96.
        # See here for the reason: http://www.ni.com/tutorial/2801/en/#:~:text=The%20secondary%20address%20is%20actually,the%20last%20bit%20is%20not
        # We return a dict looking like this {"pad": pad, "sad": None} or {"pad": pad, "sad": sad-96}
        # So we first split the string, then create a list of ints, and substract 96 from the second item (index = 1)
        result = [int(addr)-96*i for i, addr in enumerate((await super().read()).split(b" "))]
        # Create the dict, zip_longest pads the shorted list with None
        return dict(zip_longest(indices, result))

    def set_eoi(self, enabled):
        super().write(b"++eoi " + bytes(str(int(enabled)), 'ascii'))

    async def get_eoi(self):
        super().write(b"++eoi")
        return bool(int(await super().read()))

    def set_eos_mode(self, mode):
        super().write(b"++eos " + bytes(str(int(mode)), 'ascii'))

    async def get_eos_mode(self):
        super().write(b"++eos")
        return EosMode(int(await super().read()))

    def set_eot(self, enabled):
        super().write(b"++eot_enable " + bytes(str(int(enabled)), 'ascii'))

    async def get_eot(self):
        super().write(b"++eot_enable")
        return bool(int(await super().read()))

    def set_eot_char(self, character):
        super().write(b"++eot_char " + bytes(str(ord(character)), 'ascii'))

    async def get_eot_char(self):
        super().write(b"++eot_char")
        return chr(int(await super().read()))

    def remote_enable(self, enable):
        if bool(enable):
          super().write(b"++llo")

    def timeout(self, value):
        super().write(b"++read_tmo_ms " + bytes(str(int(enabled)), 'ascii'))

    def ibloc(self):
        super().write(b"++loc")

    async def ibsta(self):
        super().write(b"++status")
        return await super().read()

    def interface_clear(self):
        super().write(b"++ifc")

    def clear(self):
        super().write(b"++clr")

    def trigger(self):
        super().write(b"++trg")

    async def version(self):
        super().write(b"++ver")
        # Return a unicode string
        return (await super().read()).decode()

    def set_listen_only(self, enabled):
        super().write(b"++lon " + bytes(str(int(enabled)), 'ascii'))

    async def get_listen_only(self):
        super().write(b"++lon")
        return bool(int(await super().read()))

    async def serial_poll(self, pad=None, sad=None):
        command = b"++spoll"
        if pad is not None:
            command += b" " + bytes(str(int(pad)), 'ascii')
            if sad is not None:
                command += b" " + bytes(str(int(sad + 96)), 'ascii')
        super().write(command)

        return await super().read()

    async def test_srq(self):
        super().write(b"++srq")
        return bool(int(await super().read()))

    def reset(self):
        super().write(b"++rst")

    def set_save_config(self, enabled):
        super().write(b"++savecfg " + bytes(str(int(enabled)), 'ascii'))

    async def get_save_config(self):
        super().write(b"++savecfg")
        return bool(int(await super().read()))
