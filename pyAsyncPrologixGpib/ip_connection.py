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

    # The dict items are lists, that keep track of the connection pool
    # The list contains the following elements:
    # item = list[0, (reader, writer)]
    # The first element is the connectio count and the second is the connection tuple
    _connection_pool = {}
    _connection_pool_lock = asyncio.Lock()

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

    @property
    def __reader(self):
        if self.is_connected:
            return AsyncIPConnection._connection_pool[self.__host][1][0]
        else:
            return None

    @property
    def __writer(self):
        if self.is_connected:
            return AsyncIPConnection._connection_pool[self.__host][1][1]
        else:
            return None

    def __init__(self, timeout=None, loop=None):
        self.__loop = loop
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

    async def read(self, length=None, eol_character=None):
        eol_character = self.SEPARATOR if eol_character is None else eol_character
        if self.__reader is not None:
            try:
                with async_timeout.timeout(self.__timeout) as cm:
                    try:
                        if length is None:
                            data = await self.__reader.readuntil(eol_character)
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
        else:
            raise ConnectionError('Prologix IP Connection not connected')

    async def connect(self, host, port=1234):
        # Reuse the connection on a host:port basis
        # For example localhost and 127.0.0.1 will not be shared, because localhost might map to
        # either ::1 or 127.0.0.1

        # TODO add lock
        async with AsyncIPConnection._connection_pool_lock:
            if (host, port) not in AsyncIPConnection._connection_pool:
                with async_timeout.timeout(self.__timeout) as cm:
                    try:
                        reader, writer = await asyncio.open_connection(host, port, loop=self.__loop)
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
            
                    AsyncIPConnection._connection_pool[(host, port)] = [0, (reader, writer)]

            AsyncIPConnection._connection_pool[(host, port)][0] += 1   # increment the connection count
        self.__host = (host, port)

        self.logger.info('Prologix IP connection established to host %(host)s:%{port}d', {'host': host, 'port': port})

    async def disconnect(self):
        if self.__host is not None:
            async with AsyncIPConnection._connection_pool_lock:
                AsyncIPConnection._connection_pool[self.__host][0] -= 1   # decrement the connection count
                if AsyncIPConnection._connection_pool[self.__host][0] == 0:
                    # Close the connection only if no one is using it
                    await self.__flush()
                    del AsyncIPConnection._connection_pool[self.__host]

            self.__host = None
            self.logger.info('Prologix IP connection closed')


    async def __flush(self):
        # Flush data
        if self.__writer is not None:
            self.__writer.write_eof()
            await self.__writer.drain()
            self.__writer.close()
            await self.__writer.wait_closed()

