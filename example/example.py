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
import warnings
import sys

sys.path.append("..") # Adds main directory to python modules path.

# Devices
from pyAsyncPrologix.pyAsyncPrologix import AsyncPrologixGpibEthernetController

running_tasks = []
loop = asyncio.get_event_loop()
# The primary address 22 can be any. There is no device connection required for this example
gpib_device = AsyncPrologixGpibEthernetController('127.0.0.1', pad=22)

async def stop_loop():
    # Clean up: Disconnect ip connection and stop the consumers
    for task in running_tasks:
        task.cancel()
    try:
      await asyncio.gather(*running_tasks)
    except asyncio.CancelledError:
        pass
    loop.stop()    

def error_handler(task):
    try:
      task.result()
    except Exception:
      asyncio.ensure_future(stop_loop())

async def main():
    try:
        try: 
            await gpib_device.connect()
            version = await gpib_device.version()
            logging.getLogger(__name__).info('Controller version: %(version)s', {'version': version})

        except (ConnectionError, ConnectionRefusedError):
            logging.getLogger(__name__).error('Could not connect to remote target. Connection refused. Is the device connected?')
        finally:
            await gpib_device.disconnect()    # We may call diconnect() on a non-connected gpib device
            logging.getLogger(__name__).debug('Shutting down the main loop')
    except asyncio.CancelledError:
        # If the loop is canceled, someone else is shutting us down. That someone must then take care of closing the
        # loop.
        pass
    else:
        loop.stop()
    logging.getLogger(__name__).debug('Stopped the main loop')

# Report all mistakes managing asynchronous resources.
warnings.simplefilter('always', ResourceWarning)
loop.set_debug(enabled=True)    # Raise all execptions and log all callbacks taking longer than 100 ms
logging.basicConfig(level=logging.INFO)    # Enable logs from the ip connection. Set to debug for even more info

running_tasks.append(asyncio.ensure_future(main()))
running_tasks[-1].add_done_callback(error_handler)  # Add error handler to catch exceptions

try:
    loop.run_forever()
except KeyboardInterrupt:
  loop.run_until_complete(stop_loop())
loop.close()

