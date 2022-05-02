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
There is no error checking or reconnection done. This is left as an exercise to the user.
"""
import asyncio
import time
from asyncio import Task

from contextlib import AsyncExitStack
from decimal import Decimal
from uuid import UUID

import simplejson as json
import asyncio_mqtt
from prologix_gpib_async import AsyncPrologixGpibEthernetController

DEVICE_IP = "localhost"
MQTT_HOST = "localhost"
MQTT_TOPIC = "sensors/room_1/frequency/device_1"    # The topic, where the data is to be published
# The device id is used to uniquely identify the device on the sensor network
DEVICE_UUID = UUID('7fc6e6e5-bf24-4c45-a881-d69d299a5b69')


async def cancel_tasks(tasks: set[Task]) -> None:
    """
    Cancel all tasks and log any exceptions raised.

    Parameters
    ----------
    tasks: Iterable[asyncio.Task]
        The tasks to cancel
    """
    try:
        for task in tasks:
            if not task.done():
                task.cancel()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            # Check for exceptions, but ignore asyncio.CancelledError, which inherits from BaseException not Exception
            if isinstance(result, Exception):
                raise result
    except Exception:  # pylint: disable=broad-except
        print("Error during shutdown")


async def data_producer(gpib_device: AsyncPrologixGpibEthernetController, output_queue: asyncio.Queue[Decimal]) -> None:
    """
    Scrapes the data from the GPIB device and puts it into a queue.

    Parameters
    ----------
    gpib_device: AsyncPrologixGpibEthernetController
        The GPIB device to be read
    output_queue: asyncio.Queue
        A queue into which the resulting Decimals are put
    """
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
        await asyncio.sleep(interval - time.monotonic() + start_of_query)


async def data_consumer(
        mqtt_client: asyncio_mqtt.Client,
        input_queue: asyncio.Queue[Decimal],
        reconnect_interval: float
) -> None:
    """
    The consumer will read the data from the queue, encode it to JSON and push it to an MQTT topic.
    Parameters
    ----------
    mqtt_client: asyncio_mqtt.Client
        The client, that is connected to an MQTT server
    input_queue: asyncio.Queue
        The data queue
    reconnect_interval: float
        The number of seconds to wait between reconnection attempts
    """
    while "loop not cancelled":
        value = await input_queue.get()
        try:
            payload = {
                'timestamp': time.time(),   # A current timestamp
                'uuid': str(DEVICE_UUID),   # A unique device to
                'value': value,
            }
            # convert payload to JSON
            # Typically sensors return data as decimals or ints to preserve the precision
            payload = json.dumps(payload, use_decimal=True)
            await mqtt_client.publish(MQTT_TOPIC, payload=payload, qos=2)
        except asyncio_mqtt.error.MqttError as exc:
            print(f"MQTT error: {exc}. Retrying.")
            await asyncio.sleep(reconnect_interval)
        finally:
            input_queue.task_done()


async def main() -> None:
    """
    The main worker. It spawns the child workers for gathering the data and pushing it to the MQTT topic.
    """
    try:
        async with AsyncExitStack() as stack:
            tasks: set[Task] = set()
            data_queue = asyncio.Queue()
            stack.push_async_callback(cancel_tasks, tasks)

            gpib_device = await stack.enter_async_context(AsyncPrologixGpibEthernetController(DEVICE_IP, pad=3))
            task = asyncio.create_task(data_producer(gpib_device, output_queue=data_queue))
            tasks.add(task)
            mqtt_client = await stack.enter_async_context(asyncio_mqtt.Client(hostname=MQTT_HOST))
            task = asyncio.create_task(data_consumer(mqtt_client, input_queue=data_queue, reconnect_interval=3))
            tasks.add(task)

            await asyncio.gather(*tasks)
    except (ConnectionError, ConnectionRefusedError):
        print("Could not connect to remote target. Is the device connected?")

asyncio.run(main())
