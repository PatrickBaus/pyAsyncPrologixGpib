# -*- coding: utf-8 -*-
"""
This module provides the two classes AsyncIPConnection() and AsyncSharedIPConnection(). The shared
version uses a connection pool to reduce the number of individual connections made to the host. This
is useful for embedded devices, that can only manage a limited number of connections.
"""
import asyncio
import errno    # The error numbers can be found in /usr/include/asm-generic/errno.h
import logging


class NotConnectedError(ConnectionError):
    """
    Raised whenever the connection is not connected and there is a read or write attempt.
    """

class ConnectionLostError(ConnectionError):
    """
    Raised if the connection is terminated during a read or write.
    """

class NetworkError(ConnectionError):
    """
    Raised if the client is not reachable
    """

DEFAULT_WAIT_TIMEOUT = 1 # in seconds

class _AsyncIPConnectionPool():
    """
    An IP connection pool. This pool can be used to share connection between different device
    instances. This is important for small embedded devices, that do not have the ressources to
    handle many connections.
    """
    _connections = {}

    @classmethod
    async def connect(cls, hostname, port, timeout, client):
        """
        Either returns a new connection or if the hostname/port combination is known, returns
        an existing connection.
        For example localhost and 127.0.0.1 will not be shared, because localhost might either map
        to ::1 or 127.0.0.1

        Parameters
        ----------
        hostname: str
            hostname of the connection
        port: int
            port of the connection
        client: AsyncSharedIPConnection
            the shared ip connection
        """
        try:
            if (hostname, port) not in cls._connections:
                # Create a new connection
                cls._connections[(hostname, port)] = _AsyncPooledIPConnection(timeout=timeout)

            await cls._connections[(hostname, port)].connect_client(hostname, port, client)

            return cls._connections[(hostname, port)]
        except:
            # If there is *any* error remove the connection from the pool, unless other clients are still trying to connect
            if (hostname, port) in cls._connections and not cls._connections[(hostname, port)].has_clients:
                del cls._connections[(hostname, port)]
            # then pass on the error
            raise

    @classmethod
    async def disconnect(cls, hostname, port, client):
        """
        Removes the client from the list of connected clients. This will disconnect
        the connection if it is the last client.

        Parameters
        ----------
        hostname: str
            hostname of the connection
        port: int
            port of the connection
        client: AsyncSharedIPConnection
            the shared ip connection
        """
        if (hostname, port) in cls._connections:
            await cls._connections[(hostname, port)].disconnect_client(client)

            # If there are no clients left, remove the connection from the pool
            if not cls._connections[(hostname, port)].has_clients:
                del cls._connections[(hostname, port)]


class AsyncIPConnection():
    """
    A basic IP connection. It handles reading, writing, connecting and disconnecting an IP connection
    in Python AsyncIO.
    """
    SEPARATOR = b'\n'

    @property
    def timeout(self):
        """
        Returns
        -------
        float
            timeout for async operations in seconds
        """
        return self.__timeout

    @timeout.setter
    def timeout(self, value):
        """
        Parameters
        ----------
        value: float
            timeout of all operation in seconds
        """
        self.__timeout = abs(float(value))

    @property
    def is_connected(self):
        """
        Returns
        -------
        bool
            True if the connection is current still active.
        """
        return self.__writer is not None and not self.__writer.is_closing()

    def __init__(self, timeout=None):
        """
        Parameters
        ----------
        timeout: float, default=None
            timeout of all operation in seconds. Use DEFAULT_WAIT_TIMEOUT if None is set
        """
        self.__host, self.__writer, self.__reader = None, None, None
        self.__timeout = DEFAULT_WAIT_TIMEOUT if timeout is None else timeout

        self.__logger = logging.getLogger(__name__)
        self.__lock = None

    async def write(self, data):
        """
        Send data to the client and make sure the buffer is emptied.

        Parameters
        ----------
        data: bytes
            data to be sent to the host
        """
        self.__logger.debug('Sending data: %s', data)
        if self.is_connected:
            try:
                self.__writer.write(data)
                await self.__writer.drain()
            except ConnectionResetError:
                self.__logger.error("Connection lost while sending data to host (%s:%d).", *self.__host)
                try:
                    # This will call drain() again, and likely fail, but disconnect() should be the only place
                    # to remove the reader and writer.
                    await self.disconnect()
                except Exception:   # pylint: disable=broad-except
                        # We could get back *anything*. So we catch everything and throw it away.
                        # We are shutting down anyway.
                    self.__logger.exception("Exception during write error.")
                raise ConnectionLostError("Prologix IP Connection error. Connection lost to host %s:%d." % self.__host) from None
        else:
            raise NotConnectedError('Prologix IP Connection not connected')

    async def read(self, length=None, eol_character=None):
        """
        Read either a fixed number of bytes or until the eol_character has been found. If length is
        set, we will read a fixed number of bytes.

        Parameters
        ----------
        length: int, default=None
            number of bytes to be read if not None
        eol_character: byte, default=None
            eol character to terminate the read if length is None. If None, the default SEPARATOR is used.

        Returns
        ----------
        bytes
            data to be received from the host
        """
        if not self.is_connected:
            raise NotConnectedError('Prologix IP Connection not connected')

        async with self.__lock:
            if self.is_connected:   # We need to check again, because the connection might have closed by now
                try:
                    if length is None:
                        eol_character = self.SEPARATOR if eol_character is None else eol_character
                        coro = self.__reader.readuntil(eol_character)
                    else:
                        coro = self.__reader.readexactly(length)
                    data = await asyncio.wait_for(coro, timeout=self.__timeout)

                    self.__logger.debug("Data read: %s", data)
                    return data
                except asyncio.TimeoutError:
                    self.__logger.error('Timeout (>%d s) while reading data.', self.__timeout)
                    raise
                except asyncio.IncompleteReadError as exc:
                    if len(exc.partial) > 0:    # pylint: disable=no-else-return
                        self.__logger.warning("Incomplete read request from host (%s:%d). Check your data.", *self.__host)
                        return data
                    else:
                        self.__logger.error("Connection error. The host (%s:%d) did not reply.", *self.__host)
                        try:
                            await self.disconnect()
                        except Exception:   # pylint: disable=broad-except
                            # We could get back *anything*. So we catch everything and throw it away.
                            # We are shutting down anyway.
                            self.__logger.exception("Exception during read error.")
                        raise ConnectionLostError(f"Prologix IP Connection error. The host '%s:%d' did not reply" % *self.__host) from None
            else:
                raise NotConnectedError('Prologix IP Connection not connected')

    async def connect(self, hostname, port):
        """
        Connect to the host. If a conneciton is already established, connect() will return without
        delay.

        Parameters
        ----------
        hostname: str
            hostname to connect to
        port: int
            port to connect to
        """
        if not self.is_connected:
            try:
                self.__reader, self.__writer = await asyncio.wait_for(
                    asyncio.open_connection(host=hostname, port=port),
                    timeout=self.__timeout
                )
            except OSError as error:
                if error.errno == errno.ENETUNREACH:
                    raise NetworkError(f"Prologix IP Connection error: Cannot connect to address {hostname}:{port}") from None
                if error.errno == errno.ECONNREFUSED:
                    raise ConnectionRefusedError(f"Prologix IP Connection error: The host ({hostname}:{port}) refused to connect") from None
                raise
            except asyncio.TimeoutError:
                raise NetworkError('Prologix IP Connection error during connect: Timeout') from None

            self.__host = (hostname, port)
            self.__lock = asyncio.Lock()
            self.__logger.info('Prologix IP connection established to host %s:%d', hostname, port)

    async def disconnect(self):
        """
        Disconnect the IP connection and make sure all buffers are flushed.
        """
        if self.is_connected:
            try:
                await self.__flush()
            finally:
                # We guarantee, that the connection is removed
                self.__host, self.__writer, self.__reader = None, None, None
                self.__lock = None
                self.__logger.info('Prologix IP connection closed')

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


class _AsyncPooledIPConnection(AsyncIPConnection):
    """
    A pooled IP connection. It keeps track of the number connected clients. It will also make sure,
    that only the first client may connect to a host and the last client may disconnect.
    """
    @property
    def has_clients(self):
        """
        Returns
        -------
        bool
            True, if the connections has clients
        """
        return bool(self.__clients)

    def __init__(self, timeout=None):
        """
        Parameters
        ----------
        timeout: float, default=None
            timeout of all operation in seconds. Use DEFAULT_WAIT_TIMEOUT if None is set
        """
        super().__init__(timeout)
        self.__clients = set()
        self.meta = {}    # Meta data used to store connection specific states
        self.__lock = asyncio.Lock()

    async def connect_client(self, hostname, port, client):
        """
        Connect to the host. This function can be called multiple times by the client. It
        will return immediately if already connected and if no one is holding the lock.

        Parameters
        ----------
        hostname: str
            hostname of the connection
        port: int
            port of the connection
        client: AsyncSharedIPConnection
            the shared ip connection
        """
        if not client in self.__clients:
            # First add ourselves to the list of clients, so the connection will not be released, while we wait for
            # the release of the lock
            self.__clients.add(client)

        # Lock the connection and connect, this will return immediately, if we are connected and
        # no one is holding the lock.
        # We need the lock, because someone might be in the process of connecting or disconnecting
        # at the same time. In this case, we will either wait for the connection or reconnect
        # afterwards.
        try:
            async with self.__lock:
                await super().connect(hostname, port)
        except Exception:
            # If there is *any* error, remove ourselves from the list of connected clients
            self.__clients.remove(client)
            # then pass on the error
            raise

    async def disconnect_client(self, client):
        """
        Either removes the client from the user list or disconnect the connection if the client is
        the last user.

        Parameters
        ----------
        hostname: str
            hostname of the connection
        port: int
            port of the connection
        client: AsyncSharedIPConnection
            the shared ip connection
        """
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
    """
    A connection from the _AsyncIPConnectionPool(). Use either a AsyncSharedIPConnection or
    a AsyncIPConnection for connecting to a device.
    """
    @property
    def hostname(self):
        """
        Returns
        -------
        str
            hostname of the connection
        """
        return self.__hostname

    @property
    def meta(self):
        """
        Returns
        -------
        dict
            the connection meta data. This is the state of the underlying hardware.
        """
        if self.__conn is None:
            raise NotConnectedError('Prologix IP Connection not connected')
        return self.__conn.meta

    @property
    def port(self):
        """
        Returns
        -------
        int
            port of the connection
        """
        return self.__port

    def __init__(self, hostname, port=1234, timeout=None):
        self.__timeout = DEFAULT_WAIT_TIMEOUT if timeout is None else timeout
        self.__hostname = hostname
        self.__port = port
        self.__conn = None

    async def connect(self):
        """
        Get a connection from the connection pool.
        """
        self.__conn = await _AsyncIPConnectionPool.connect(hostname=self.__hostname, port=self.__port, timeout=self.__timeout, client=self)

    async def disconnect(self):
        """
        Return the connection to the connection pool.
        """
        try:
            if self.__conn is not None:
                await _AsyncIPConnectionPool.disconnect(hostname=self.__hostname, port=self.__port, client=self)
        finally:
            self.__conn = None

    async def write(self, data):
        """
        Writes to the underlying conenction.

        Parameters
        ----------
        data: bytes
            data to be sent to the host

        Raises
        ----------
        NotConnectedError
            if the connection is no longer connected
        """
        if self.__conn is None:
            raise NotConnectedError('Prologix IP Connection not connected')
        await self.__conn.write(data)

    async def read(self, length=None, eol_character=None):
        """
        Reads from the underlying connection. Throws a NotConnectedError() if the connection is not
        connected.

        Parameters
        ----------
        length: int, default=None
            number of bytes to be read if not None
        eol_character: byte, default=None
            eol character to terminate the read if length is None. If None, the default SEPARATOR is used.

        Returns
        ----------
        bytes
            data to be received from the host

        Raises
        ----------
        NotConnectedError
            if the connection is no longer connected
        """
        if self.__conn is None:
            raise NotConnectedError('Prologix IP Connection not connected')
        return await self.__conn.read(length, eol_character)
