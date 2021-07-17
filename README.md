# prologix_gpib_async
Python3 AsyncIO Prologix GPIB Driver. This library requires Python [asyncio](https://docs.python.org/3/library/asyncio.html). In contrast to a synchronous implementation, this library makes it possible to control multiple GPIB controllers at once and work with large setups.

## Supported Hardware
|Device|Supported|Tested|Comments|
|--|--|--|--|
|[GPIB-ETHERNET Controller 1.2](http://prologix.biz/gpib-ethernet-controller.html)|:heavy_check_mark:|:heavy_check_mark:|  |
|[GPIB-USB Controller 6.0](http://prologix.biz/gpib-usb-controller.html)|:x:|:x:|Need hardware

Tested using Linux, should work for Mac OSX, Windows and any OS with Python support.

## Setup

To install the library, clone the repository into your project folder and run the install script.

```bash
virtualenv env  # virtual environment, optional
source env/bin/activate
pip python3 setup.py install
```

## Usage

Initialize the GPIB adapter
```python
from prologix_gpib_async.prologix_gpib_async import AsyncPrologixGpibEthernetController
# Create a controller and talk to device address 22
gpib_device = AsyncPrologixGpibEthernetController("127.0.0.1", pad=22)

# Connect to the controller. This must be done inside the loop
await gpib_device.connect()

# Add your code here

# Disconnect after we are done
await gpib_device.disconnect()
```

Sending a "my command" command to address 22 (as set up previously)
```python
await await gpib_device.write("my command")
```

Reading data from address 22
```python
data = await gpib_device.read()
print(data)
```

Example programm, that queries the version string as can be found at [examples/example.py](examples/example.py)
```python
import asyncio

# Devices
from prologix_gpib_async.prologix_gpib_async import AsyncPrologixGpibEthernetController

# The primary address (e.g. 22) can be anything. There is no device connection required for this example
gpib_device = AsyncPrologixGpibEthernetController('127.0.0.1', pad=22)

async def main():
    try: 
        # Connect to the controller. This call must be done in the loop.
        await gpib_device.connect()
        version = await gpib_device.version()
        print("Controller version:", version)
    except (ConnectionError, ConnectionRefusedError):
        print("Could not connect to remote target. Is the device connected?")
    finally:
        # Disconnect from the GPIB controller. We may safely call diconnect() on a non-connected gpib device
        # in case of a connection error
        await gpib_device.disconnect()

asyncio.run(main())
```

See [examples/](examples/) for more working examples.

## Support for Multiple Devices
The Prologix GPIB adapter supports talking to multiple devices, but there is a are (theoretical) hardware limits. The Prologix adapters do not have line drivers, so only a limited number of devices can be driven using one controller.

On the software side, there is full support for multiple devices and the driver will switch between different addresses transparently. The driver internally manages the connection and keeps track of the GPIB controller state and manages the state for each gpib object. It is important, that the driver is the only client editing the state of the GPIB controller. Otherwise, the driver state and the controller state may get out of sync.

> :warning: **Concurrency with multiple devices**: Note, that when using a single adapter to control multiple devices, there is no concurrency on the GPIB bus. Whenever reading or writing to a remote device, the driver will lock the GPIB controller to ensure that reading from a controller is synchronous. This means, there is **no** speed increase, when making asynchronous reads from multiple devices on the bus. Using a GPIB Group Execute Trigger (GET) by invoking the trigger() function, concurrent measurements can be triggered though.

Example:
```python
import asyncio

# Devices
from prologix_gpib_async.prologix_gpib_async import AsyncPrologixGpibEthernetController

gpib_device1 = AsyncPrologixGpibEthernetController("127.0.0.1", pad=22)
gpib_device2 = AsyncPrologixGpibEthernetController("127.0.0.1", pad=10)

async def main():
    try: 
        # Connect to the two devices. This call must be done in the loop.
        await asyncio.gather(
          gpib_device1.connect(),
          gpib_device2.connect(),
        )
        await gpib_device1.write(b'*IDN?')    # Automatically changes address to device 22
        print(await gpib_device1.read())
        await gpib_device2.write(b'*IDN?')    # Automatically changes address to device 10
        print(await gpib_device2.read())
    except (ConnectionError, ConnectionRefusedError):
        print("Could not connect to remote target. Is the device connected?")
    finally:
        # Disconnect from the GPIB controller. We may safely call diconnect() on a non-connected gpib device,
        # in case of a connection error
        await gpib_device.disconnect()

asyncio.run(main())
```

## Versioning

I use [SemVer](http://semver.org/) for versioning. For the versions available, see the [tags on this repository](https://github.com/PatrickBaus/pyAsyncPrologix/tags). 

## Documentation
I use the [Numpydoc](https://numpydoc.readthedocs.io/en/latest/format.html) style for documentaion.

## Authors

* **Patrick Baus** - *Initial work* - [PatrickBaus](https://github.com/PatrickBaus)

## License


This project is licensed under the GPL v3 license - see the [LICENSE](LICENSE) file for details

