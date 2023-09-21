[![pylint](../../actions/workflows/pylint.yml/badge.svg)](../../actions/workflows/pylint.yml)
[![PyPI](https://img.shields.io/pypi/v/prologix-gpib-async)](https://pypi.org/project/prologix-gpib-async/)
![PyPI - Python Version](https://img.shields.io/pypi/pyversions/prologix-gpib-async)
![PyPI - Status](https://img.shields.io/pypi/status/prologix-gpib-async)
[![License: GPL v3](https://img.shields.io/badge/License-GPL%20v3-blue.svg)](LICENSE)
[![code style](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
# prologix_gpib_async
Python3 AsyncIO Prologix GPIB Driver. This library requires Python
[asyncio](https://docs.python.org/3/library/asyncio.html). In contrast to a synchronous implementation, this library
makes it possible to control multiple GPIB controllers at once and work with large setups.

The library is fully type-hinted.

## Supported Hardware
|Device|Supported|Tested|Comments|
|--|--|--|--|
|[GPIB-ETHERNET Controller 1.2](http://prologix.biz/gpib-ethernet-controller.html)|:heavy_check_mark:|:heavy_check_mark:|  |
|[GPIB-USB Controller 6.0](http://prologix.biz/gpib-usb-controller.html)|:x:|:x:|Need hardware

Tested using Linux, should work for Mac OSX, Windows and any OS with Python support.

## Setup
To install the library in a virtual environment (always use venvs with every project):

```bash
python3 -m venv env  # virtual environment, optional
source env/bin/activate
pip install prologix-gpib-async
```

## Usage
This library makes use of asynchronous context managers to hide all connection related stuff and
also handle cleanup. By the way: Context managers are great!

Initialize the GPIB adapter
```python
from prologix_gpib_async import AsyncPrologixGpibEthernetController

# Create a controller and talk to device address 22
async with AsyncPrologixGpibEthernetController("127.0.0.1", pad=22) as gpib_device:
    # Add your code here
    ...
```

Sending a "my command" command to address 22 (as set up previously)
```python
await gpib_device.write("my command")
```

Reading data from address 22
```python
data = await gpib_device.read()
```

Example program, that queries the version string as can be found at [examples/example.py](examples/example.py)
```python
import asyncio

# Devices
from prologix_gpib_async import AsyncPrologixGpibEthernetController


async def main():
    try:
        async with AsyncPrologixGpibEthernetController("127.0.0.1", pad=22) as gpib_device:
            version = await gpib_device.version()
            print("Controller version:", version)
    except (ConnectionError, ConnectionRefusedError):
        print("Could not connect to remote target. Is the device connected?")


asyncio.run(main())
```

See [examples/](examples/) for more working examples.

## Support for Multiple Devices
The Prologix GPIB adapter supports talking to multiple devices, but there are (theoretical) hardware limits. The
Prologix adapters do not have line drivers, so only a limited number of devices can be driven using one controller.

On the software side, there is full support for multiple devices and the driver will switch between different addresses
transparently. The driver internally manages the connection and keeps track of the GPIB controller state and manages the
state for each gpib object. It is important, that the driver is the only client editing the state of the GPIB
controller. Otherwise, the driver state and the controller state may get out of sync.

> :warning: **Concurrency with multiple devices**: Note, that when using a single adapter to control multiple devices,
> there is no concurrency on the GPIB bus. Whenever reading or writing to a remote device, the driver will lock the GPIB
> controller to ensure that reading from a controller is synchronous. This means, there is **no** speed increase, when
> making asynchronous reads from multiple devices on the bus. Using a GPIB Group Execute Trigger (GET) by invoking the
> trigger() function, concurrent measurements can be triggered though. Some devices also allow asynchronous function
> calls, that signal status updates via the srq register.

Example:
```python
import asyncio
from contextlib import AsyncExitStack

# Devices
from prologix_gpib_async import AsyncPrologixGpibEthernetController

ip_address = "127.0.0.1"


async def main():
    try:
        async with AsyncExitStack() as stack:
            gpib_device1, gpib_device2 = await asyncio.gather(
                stack.enter_async_context(AsyncPrologixGpibEthernetController(ip_address, pad=22)),
                stack.enter_async_context(AsyncPrologixGpibEthernetController(ip_address, pad=10)),
            )
            await gpib_device1.write(b"*IDN?")  # Automatically changes address to device 22
            print(await gpib_device1.read())
            await gpib_device2.write(b"*IDN?")  # Automatically changes address to device 10
            print(await gpib_device2.read())
    except (ConnectionError, ConnectionRefusedError):
        print("Could not connect to remote target. Is the device connected?")


asyncio.run(main())
```

## Versioning
I use [SemVer](http://semver.org/) for versioning. For the versions available, see the
[tags on this repository](../../tags).

## Documentation
I use the [Numpydoc](https://numpydoc.readthedocs.io/en/latest/format.html) style for documentation.

## Authors
* **Patrick Baus** - *Initial work* - [PatrickBaus](https://github.com/PatrickBaus)

## License
This project is licensed under the GPL v3 license - see the [LICENSE](LICENSE) file for details
