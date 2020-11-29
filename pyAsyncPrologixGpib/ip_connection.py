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
import errno    # The error numbers can be found in /usr/include/asm-generic/errno.h
import logging
import weakref


class NotConnectedError(ConnectionError):
    pass

class ConnectionLostError(ConnectionError):
    def __init__(self, message, host, port):
        super().__init__(message)

        self.__host = host
        self.__port = port

class NetworkError(ConnectionError):
    pass

DEFAULT_WAIT_TIMEOUT = 1 # in seconds

class AsyncIPConnectionPool():
    _connections = {}

    @classmethod
    async def connect(cls, hostname, port, timeout, client):
        # Reuse the connection on a hostname:port basis
        # For example localhost and 127.0.0.1 will not be shared, because localhost might map to
        # either ::1 or 127.0.0.1

        try:
            if (hostname, port) not in cls._connections:
                # Create a new connection
                cls._connections[(hostname, port)] = AsyncPooledIPConnection(timeout=timeout)

            await cls._connections[(hostname, port)].connect(hostname, port, client)

            return cls._connections[(hostname, port)]
        except:
            # If there is *any* error remove the connection from the pool, unless other clients are still trying to connect
            if (hostname, port) in cls._connections and not cls._connections[(hostname, port)].has_clients:
                del cls._connections[(hostname, port)]
            # then pass on the error
            raise

    @classmethod
    async def disconnect(cls, hostname, port, client):
        if (hostname, port) in cls._connections:
            await cls._connections[(hostname, port)].disconnect(client)

            # If there are no clients left, remove the connection from the pool
            if not cls._connections[(hostname, port)].has_clients:
                del cls._connections[(hostname, port)]


class AsyncIPConnection():
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
        return self.__writer is not None and not self.__writer.is_closing()

    def __init__(self, timeout=None):
        self.__host, self.__writer, self.__reader = None, None, None
        self.__timeout = DEFAULT_WAIT_TIMEOUT if timeout is None else timeout

        self.__logger = logging.getLogger(__name__)

    async def write(self, data):
        self.logger.debug('Sending data: %(payload)s', {'payload': data})
        if self.is_connected:
            try:
                self.__writer.write(data)
                await self.__writer.drain()
            except ConnectionResetError:
                self.__logger.error("Connection lost while sending data to host (%s:%d).", *self.__host)
                try:
                    # This will call drain() again, and likely fail, but __disconnect() should be the only place
                    # to remove the reader and writer.
                    await self.__disconnect()
                except:
                    pass
                raise ConnectionLostError("Prologix IP Connection error. Connection lost.", host=host, port=port) from None
        else:
            raise NotConnectedError('Prologix IP Connection not connected')

    async def read(self, length=None, eol_character=None):
        if self.is_connected:
            eol_character = self.SEPARATOR if eol_character is None else eol_character
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
                self.logger.error('Timout while reading data.')
                raise
            except asyncio.IncompleteReadError as e:
                if len(e.partial) > 0:
                    self.__logger.warning("Incomplete read request from host (%s:%d). Check your data.", *self.__host)
                    return data
                else:
                    self.__logger.error("Connection error. The host (%s:%d) did not reply.", *self.__host)
                    try:
                        await self.__disconnect()
                    except:
                        pass
                    raise ConnectionLostError("Prologix IP Connection error. The host did not reply.", host=host, port=port) from None
        else:
            raise NotConnectedError('Prologix IP Connection not connected')

    async def connect(self, hostname, port):
        if not self.is_connected:
            with async_timeout.timeout(self.__timeout) as cm:
                try:
                    self.__reader, self.__writer = await asyncio.open_connection(hostname, port)
                except asyncio.CancelledError:
                    if cm.expired:
                        raise asyncio.TimeoutError() from None
                    else:
                        raise
                except OSError as error:
                    if error.errno == errno.ENETUNREACH:
                        raise NetworkError(f"Prologix IP Connection error: Cannot connect to address {hostname}:{port}") from None
                    elif error.errno == errno.ECONNREFUSED:
                        raise ConnectionRefusedError(f"Prologix IP Connection error: The host ({hostname}:{port}) refused to connect.") from None
                    else:
                        raise
                except asyncio.TimeoutError:
                    raise NetworkError('Prologix IP Connection error during connect: Timeout') from None

                self.__host = (hostname, port)

            self.logger.info('Prologix IP connection established to host %(hostname)s:%{port}d', {'hostname': hostname, 'port': port})

    async def __disconnect(self):
        if self.is_connected:
            try:
                await self.__flush()
            finally:
                # We guarantee, that the connection is removed
                self.__host, self.__writer, self.__reader = None, None, None

            self.logger.info('Prologix IP connection closed')

    async def disconnect(self):
        await self.__disconnect()

    async def __flush(self):
        # Flush data
        try:
            self.__writer.write_eof()
            await self.__writer.drain()
            self.__writer.close()
            await self.__writer.wait_closed()
        except OSError as exc:
            if exc.errno == errno.ENOTCONN:
                pass # Socket is no longer connected, so we can't send the EOF.
            else:
                raise


class AsyncPooledIPConnection(AsyncIPConnection):
    @property
    def has_clients(self):
      """
      Returns True, if the connections has clients
      """
      return bool(len(self.__clients))

    def __init__(self, timeout=None):
        super().__init__(timeout)
        self.__clients = set()
        self.__lock = asyncio.Lock()
        self.__logger = logging.getLogger(__name__)

    async def connect(self, hostname, port, client):
        if not client in self.__clients:
            # First add ourselves to the list of clients, so the connection will not be released, while we wait for
            # the release of the lock
            self.__clients.add(client)

        # Lock the connection and connect, this will return immediately, if we are connected.
        # We need the lock, because someone might be connecting or disconnecting at the same time
        try:
            async with self.__lock:
                await super().connect(hostname, port)
        except:
            # If there is *any* error, remove ourselves from the list of connected clients
            self.__clients.remove(client)
            # then pass on the error
            raise

    async def disconnect(self, client):
        # Return immediately if this client is not registered
        if client in self.__clients:
            try:
                # If we are the last client connected, lock the connection and terminate it
                if len(self.__clients) == 1:
                    # Lock the connection
                    async with self.__lock:
                        await super().disconnect()
            finally:
                # Always remove the client, no matter what happened
                self.__clients.remove(client)


class AsyncSharedIPConnection():
    def __init__(self, timeout=None):
        self.__timeout = DEFAULT_WAIT_TIMEOUT if timeout is None else timeout
        self.__host = None
        self.__conn = None

    async def connect(self, hostname, port=1234):
        self.__conn = await AsyncIPConnectionPool.connect(hostname=hostname, port=port, timeout=self.__timeout, client=self)
        self.__host = (hostname, port)

    async def disconnect(self):
        try:
            if self.__conn is not None:
                hostname, port = self.__host
                await AsyncIPConnectionPool.disconnect(hostname=hostname, port=port, client=self)
        finally:
            self.__host = None
            self.__conn = None

    async def write(self, data):
        await self.__conn.write(data)

    async def read(self, length=None, eol_character=None):
        return await self.__conn.read(length, eol_character)
