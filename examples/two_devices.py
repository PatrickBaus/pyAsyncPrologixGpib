#!/usr/bin/env python3
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

# Devices
from prologix_gpib_async import AsyncPrologixGpibEthernetController

ip_address = "localhost"


async def main():
    try:
        async with AsyncPrologixGpibEthernetController(ip_address, pad=22) as gpib_device1,\
                AsyncPrologixGpibEthernetController(ip_address, pad=10) as gpib_device2:
            await gpib_device1.write(b'*IDN?')    # Automatically changes address to device 22
            print(await gpib_device1.read())
            await gpib_device2.write(b'*IDN?')    # Automatically changes address to device 10
            print(await gpib_device2.read())
    except (ConnectionError, ConnectionRefusedError):
        print("Could not connect to remote target. Is the device connected?")

asyncio.run(main())
