# -*- coding: utf-8 -*-
# ##### BEGIN GPL LICENSE BLOCK #####
#
# Copyright (C) 2020  Patrick Baus
#
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
import async_timeout
import logging


DEFAULT_WAIT_TIMEOUT = 1 # in seconds

class AsyncIPConnection(object):
    SEPARATOR = b'\n'

    @property
    def timeout(self):
        """
        Returns the timeout for async operations in seconds
        """
        return self.__timeout

    @timeout.setter
    def timeout(self, value):
        self.__timeout = abs(int(value))

    @property
    def logger(self):
        return self.__logger

    @property
    def is_connected(self):
        return self.__host is not None

    def __init__(self, timeout=None, loop=None):
        self.__loop = loop
        self.__reader, self.__writer = None, None
        self.__host = None
        self.__timeout = DEFAULT_WAIT_TIMEOUT if timeout is None else timeout

        self.__logger = logging.getLogger(__name__)

    async def write(self, data):
        self.logger.debug('Sending data: %(payload)s', {'payload': data})
        if self.__writer is not None:
            self.__writer.write(data)
            await self.__writer.drain()
        else:
            raise ConnectionError('Prologix IP Connection not connected')

    async def read(self, length=None):
        try:
            with async_timeout.timeout(self.__timeout) as cm:
                try:
                    if length is None:
                        data = await self.__reader.readuntil(self.SEPARATOR)
                    else:
                        data = await self.__reader.readexactly(length)
                    self.__logger.debug("Data read: %(data)s", {'data': data})
                    return data
                except asyncio.CancelledError:
                    if cm.expired:
                        raise asyncio.TimeoutError() from None
                    else:
                        raise
        except asyncio.TimeoutError:
            self.logger.exception('Timout while reading data.')
            raise

    async def connect(self, host, port=1234):
        with async_timeout.timeout(1) as cm:  # 1s timeout
            try:
                self.__reader, self.__writer = await asyncio.open_connection(host, port, loop=self.__loop)
            except asyncio.CancelledError:
                if cm.expired:
                    raise asyncio.TimeoutError() from None
                else:
                    raise
            except OSError as error:
                if error.errno == 101:
                  raise ConnectionError(f"Prologix IP Connection error during connection: Cannot connect to address {host}:{port}") from None
                else:
                  raise
            except:
                raise ConnectionError('Prologix IP Connection error during connection: Timeout')
        self.__host = host
        self.logger.info('Prologix IP connection established to host %(host)s', {'host': self.__host})

    async def disconnect(self):
        self.__host = None
        await self.__flush()
        self.logger.info('Prologix IP connection closed')

    async def __flush(self):
        self.__reader = None
        # Flush data
        if self.__writer is not None:
            self.__writer.write_eof()
            await self.__writer.drain()
            self.__writer.close()
            await self.__writer.wait_closed()
            self.__writer = None

