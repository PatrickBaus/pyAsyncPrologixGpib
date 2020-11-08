# pyAsyncPrologixGpib
Python3 AsyncIO Prologix GPIB Driver. This library requires Python [asyncio](https://docs.python.org/3/library/asyncio.html). In contrast to a synchronous implementation, this library makes it possible to control multiple GPIB controllers at once and work with large setups.

## Supported Hardware
|Device|Supported|Tested|Comments|
|--|--|--|--|
|[GPIB-ETHERNET Controller 1.2](http://prologix.biz/gpib-ethernet-controller.html)|:heavy_check_mark:|  :heavy_check_mark:|  |
|[GPIB-USB Controller 6.0](http://prologix.biz/gpib-usb-controller.html)|:x:|:x:|Need hardware

Tested using Linux, should work for Mac OSX, Windows and any OS with Python support.

## Setup

There are currently no packages available. To install the library clone the reposistory into your project folder.

## Usage

Initialize the GPIB adapter
```python
from pyAsyncPrologixGpib.pyAsyncPrologixGpib import AsyncPrologixGpibEthernetController
# Create a controller and talk to device address 22
gpib_device = AsyncPrologixGpibEthernetController('127.0.0.1', pad=22)

# Connect to the controller. This must be done inside the loop
await gpib_device.connect()

# Add your code here

# Disconnect after we are done
await gpib_device.disconnect()
```

Sending a "my command" command to address 22 (as set up previously)
```python
await await gpib_device.write(msg)("my command")
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
from pyAsyncPrologixGpib.pyAsyncPrologixGpib import AsyncPrologixGpibEthernetController

# The primary address (e.g. 22) can be anything. There is no device connection required for this example
gpib_device = AsyncPrologixGpibEthernetController('127.0.0.1', pad=22)

async def main():
    try: 
        # Connect to the controller. This call must be done in the loop.
        await gpib_device.connect()
        version = await gpib_device.version()
        print("Controller version: ", version)
    except (ConnectionError, ConnectionRefusedError):
        print("Could not connect to remote target. Connection refused. Is the device connected?")
    finally:
        # Disconnect from the GPIB controller. We may safely call diconnect() on a non-connected gpib device, that
        # means in case of a connection error
        await gpib_device.disconnect()

asyncio.run(main())
```

See [examples/](examples/) for more working examples.

## Support for Multiple Devices
The Prologix GPIB adapter supports talking to multiple devices, but there are caveats. First of all there are hardware limitations, as the Prologix adapters do not have line drivers. So the GPIB cable length and number of devices is seriously limited. On the software side, there is no way to read or write a specific device with a single command. One has to switch back and forth using the '++adr' command. This is not so much of a problem with the USB adapter as one instance of a program typically has exclusive access to the serial resource. From the library point of view, the only thing one would have to do is to keep track of the internal state of the adapter and update the controller to match different device setups, when switching between devices. Regarding the Ethernet controller, the problem is escalated, because 'anyone' on the network can change the internal state of the adapter and there is no way to track this.

To avoid both the hardware limitations and the software issues, I recommend using one controller per device.

Although, this module does not have integrated support for multiple instances. It is still possible to create them and use multiple devices with it. One only has to make sure to call to the 'set_address()' function and all other configuration related functions before talking to the devices.

## Versioning

I use [SemVer](http://semver.org/) for versioning. For the versions available, see the [tags on this repository](https://github.com/PatrickBaus/pyAsyncPrologix/tags). 

## Authors

* **Patrick Baus** - *Initial work* - [PatrickBaus](https://github.com/PatrickBaus)

## License


This project is licensed under the GPL v3 license - see the [LICENSE](LICENSE) file for details

