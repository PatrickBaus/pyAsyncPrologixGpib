#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ##### BEGIN GPL LICENSE BLOCK #####
#
# Copyright (C) 2022  Patrick Baus
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
"""
This is an example for a very simple data logger, that reads data from a GPIB device and pushes it to an MQTT topic.
The device used for this example is a standard SCPI capable HP53131A universal counter and the data read is a frequency.
There is only little error checking or handling. This is left as an exercise to the user.
"""
from __future__ import annotations

import asyncio
import time
from asyncio import Task

from decimal import Decimal
from uuid import UUID

import simplejson as json
import asyncio_mqtt
from prologix_gpib_async import AsyncPrologixGpibEthernetController

DEVICE_IP = "localhost"
GPIB_PAD = 3    # The GPIB address of the device
MQTT_HOST = "localhost"
MQTT_TOPIC = "sensors/room_1/frequency/device_1"    # The topic, where the data is to be published
# The device id is used to uniquely identify the device on the sensor network
DEVICE_UUID = UUID('7fc6e6e5-bf24-4c45-a881-d69d299a5b69')


async def data_producer(output_queue: asyncio.Queue[Decimal], reconnect_interval: float) -> None:
    """
    Scrapes the data from the GPIB device and puts it into a queue.

    Parameters
    ----------
    output_queue: asyncio.Queue
        A queue into which the resulting Decimals are put
    reconnect_interval: float
        The number of seconds to wait between reconnection attempts
    """
    while "loop not cancelled":
        try:
            async with AsyncPrologixGpibEthernetController(DEVICE_IP, pad=GPIB_PAD) as gpib_device:
                print(f"Connected to {gpib_device}")
                # Run the initial config
                interval = 10   # Read data at `interval` seconds
                await gpib_device.write(b'*RST')
                await gpib_device.write(b':INP1:COUP AC')
                await gpib_device.write(b':INP1:IMP 50')
                await gpib_device.write(b':FREQ:ARM:STOP:SOUR DIG')
                await gpib_device.write(b':FREQ:ARM:STOP:DIG 8')
                await gpib_device.write(b':INIT:CONT ON')
                # Then start reading the data
                while "Connected":
                    start_of_query = time.monotonic()
                    await gpib_device.write(b':ABORt')
                    await gpib_device.write(b':FETCh?')
                    value = await gpib_device.read()
                    value = Decimal(value[:-1].decode("utf8"))
                    output_queue.put_nowait(value)
                    print(f"Read: {value} Hz")
                    await asyncio.sleep(interval - time.monotonic() + start_of_query)
        except asyncio.TimeoutError:
            print("Timeout received. Restarting")
            await asyncio.sleep(reconnect_interval)
        except (ConnectionError, ConnectionRefusedError) as exc:
            print(f"Could not connect to remote target ({exc}). Is the device connected?")
            await asyncio.sleep(reconnect_interval)


async def data_consumer(
        input_queue: asyncio.Queue[Decimal],
        reconnect_interval: float
) -> None:
    """
    The consumer will read the data from the queue, encode it to JSON and push it to an MQTT topic.
    Parameters
    ----------
    input_queue: asyncio.Queue
        The data queue
    reconnect_interval: float
        The number of seconds to wait between reconnection attempts
    """
    payload: str | None = None
    while "not connected":
        try:
            async with asyncio_mqtt.Client(MQTT_HOST) as mqtt_client:
                while "loop not cancelled":
                    # Only get a new value from the queue, if we have successfully sent it to the network
                    if payload is None:
                        value = await input_queue.get()
                    # convert payload to JSON
                    # Typically sensors return data as decimals or ints to preserve the precision
                    payload = json.dumps(
                        {
                            'timestamp': time.time(),  # The current timestamp
                            'uuid': str(DEVICE_UUID),  # The unique device id to identify the sender on the network
                            'value': value,
                        },
                        use_decimal=True
                    )
                    await mqtt_client.publish(MQTT_TOPIC, payload=payload, qos=2)
                    payload = None
                    input_queue.task_done()  # finally mark the job as done
        except asyncio_mqtt.error.MqttError as exc:
            print(f"MQTT error: {exc}. Retrying.")
            await asyncio.sleep(reconnect_interval)


async def main() -> None:
    """
    The main worker. It spawns the child workers for gathering the data and pushing it to the MQTT topic.
    """
    tasks: set[Task] = set()
    try:
        data_queue = asyncio.Queue()

        task = asyncio.create_task(data_producer(output_queue=data_queue, reconnect_interval=3))
        tasks.add(task)
        task = asyncio.create_task(data_consumer(input_queue=data_queue, reconnect_interval=3))
        tasks.add(task)

        await asyncio.gather(*tasks)
    finally:
        # Cancel all tasks
        [task.cancel() for task in tasks if not task.done()]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            # Check for exceptions, but ignore asyncio.CancelledError, which inherits from BaseException not Exception
            if isinstance(result, Exception):
                print("Error during shutdown:", result)

asyncio.run(main())
