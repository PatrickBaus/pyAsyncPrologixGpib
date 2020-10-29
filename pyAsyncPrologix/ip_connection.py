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


DEFAULT_WAIT_TIMEOUT = 2.5 # in seconds

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

    def __init__(self, loop):
        self.__loop = loop
        self.__reader, self.__writer = None, None
        self.__host = None
        self.__timeout = DEFAULT_WAIT_TIMEOUT

        self.__logger = logging.getLogger(__name__)

    def write(self, data):
        self.logger.debug('Sending data: %(payload)s', {'payload': data})
        self.__writer.write(data)

    async def read(self):
        try:
            with async_timeout.timeout(self.__timeout) as cm:
                try:
                    return await self.__reader.readuntil(self.SEPARATOR)
                except asyncio.CancelledError:
                    if cm.expired:
                        raise asyncio.TimeoutError() from None
                    else:
                        raise
                except:
                  self.logger.exception('Error while reading data.')
                  return None
        except asyncio.TimeoutError:
            return None

    async def connect(self, host, port=1234):
        self.__host = host
        self.__reader, self.__writer = await asyncio.open_connection(host, port, loop=self.__loop)
        self.logger.info('Prologix IP connection established to host %(host)s', {'host': self.__host})

    async def disconnect(self):
        await self.__flush()
        self.__host = None
        self.logger.info('Prologix IP connection closed')

    async def __flush(self):
        self.__reader = None
        # Flush data
        if self.__writer is not None:
            self.__writer.write_eof()
            await self.__writer.drain()
            self.__writer.close()
            self.__writer = None

