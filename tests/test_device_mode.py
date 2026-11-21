"""Tests for the GPIB device mode classes."""

import pytest

from prologix_gpib_async import AsyncPrologixGpibEthernetDevice


def test_device_can_be_constructed():
    """The constructor must not call the public set_wait_delay(), which is disabled in device mode."""
    device = AsyncPrologixGpibEthernetDevice("127.0.0.1", pad=5)
    assert device.pad == 5


def test_device_set_wait_delay_still_unsupported():
    """The public method stays disabled in device mode."""
    device = AsyncPrologixGpibEthernetDevice("127.0.0.1", pad=5)
    with pytest.raises(TypeError):
        device.set_wait_delay(0.5)
