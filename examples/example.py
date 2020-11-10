#!/usr/bin/env python3
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
import sys

sys.path.append("..") # Adds main directory to python modules path.

# Devices
from pyAsyncPrologixGpib.pyAsyncPrologixGpib import AsyncPrologixGpibEthernetController

# The primary address (e.g. 22) can be anything. There is no device connection required for this example
gpib_device = AsyncPrologixGpibEthernetController('192.168.1.104', pad=22)

async def main():
    try: 
        # Connect to the controller. This call must be done in the loop.
        await gpib_device.connect()
        version = await gpib_device.version()
        print('Controller version: ', version)
    except (ConnectionError, ConnectionRefusedError):
        print('Could not connect to remote target. Connection refused. Is the device connected?')
    finally:
        # Disconnect from the GPIB controller. We may safely call diconnect() on a non-connected gpib device, that
        # means in case of a connection error
        await gpib_device.disconnect()

asyncio.run(main())

