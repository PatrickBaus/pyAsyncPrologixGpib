"""Shared fixtures for the test suite."""

import pytest

from prologix_gpib_async.ip_connection import _AsyncIPConnectionPool


@pytest.fixture(autouse=True)
def empty_connection_pool():
    """
    The connection pool is a class attribute, so a connection leaked by one test would be shared with the next one.
    Make sure every test releases its connections.
    """
    assert not _AsyncIPConnectionPool._connections  # pylint: disable=protected-access
    yield
    leaked = dict(_AsyncIPConnectionPool._connections)  # pylint: disable=protected-access
    _AsyncIPConnectionPool._connections.clear()  # pylint: disable=protected-access
    assert not leaked, f"Connections left in the pool: {list(leaked)}"
