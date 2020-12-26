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
import logging
import sys

sys.path.append("..") # Adds main directory to python modules path.

# Devices
from pyAsyncPrologixGpib.pyAsyncPrologixGpib import AsyncPrologixGpibEthernetController
from pyAsyncPrologixGpib.ip_connection import NotConnectedError, ConnectionLostError, NetworkError

# The primary address (e.g. 22) can be anything. There is no device connection required for this example
ip_address = '192.168.1.104'
gpib_device1 = AsyncPrologixGpibEthernetController(ip_address, pad=22)

gpib_device2 = AsyncPrologixGpibEthernetController(ip_address, pad=10)

async def main():
    try: 
        # Connect to the controller. This call must be done in the loop.
        await asyncio.gather(
          gpib_device1.connect(),
          gpib_device2.connect(),
        )
        await gpib_device1.write(b"*IDN?")    # Automatically changes address to device 22
        print(await gpib_device1.read())
        await gpib_device2.write(b"*IDN?")    # Automatically changes address to device 10
        print(await gpib_device2.read())
    except (ConnectionRefusedError, NetworkError):
        logging.getLogger(__name__).error('Could not connect to remote target. Connection refused. Is the device connected?')
        raise
    except NotConnectedError:
        logging.getLogger(__name__).error('Not connected. Did you call .connect()?')
    finally:
        # Disconnect from the GPIB controller. We may safely call diconnect() on a non-connected gpib device, even
        # in case of a connection error
        await asyncio.gather(
          gpib_device1.disconnect(),
          gpib_device2.disconnect(),
        )

logging.basicConfig(level=logging.DEBUG)    # Enable logs from the ip connection. Set to logging.INFO for less verbose output
asyncio.run(main())

