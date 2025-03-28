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
"""A simple example to demonstrate operating a single SCPI device via the Prologix GPIB adapter."""

import asyncio

# Devices
from prologix_gpib_async import AsyncPrologixGpibEthernetController


async def main():
    """This example will print the controller version and the ID of the attached SCPI device"""
    try:
        # The primary address (e.g. 22) can be anything in range(1,31).
        # There is no device connection required for this example
        async with AsyncPrologixGpibEthernetController("localhost", pad=22) as gpib_device:
            version = await gpib_device.version()
            print("Controller version:", version)
            await gpib_device.write(b"*IDN?")
            # Instruct the controller to  read until the device sets <EOI>, then read until '\n'
            # from the prologix controller
            device_id = await gpib_device.read()
            print("SCPI device id:", device_id)
    except (ConnectionError, ConnectionRefusedError):
        print("Could not connect to remote target. Is the device connected?")


asyncio.run(main())
