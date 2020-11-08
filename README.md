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

See examples/example.py for a fully working example, that queries the version number of the controller.

## Versioning

I use [SemVer](http://semver.org/) for versioning. For the versions available, see the [tags on this repository](https://github.com/PatrickBaus/pyAsyncPrologix/tags). 

## Authors

* **Patrick Baus** - *Initial work* - [PatrickBaus](https://github.com/PatrickBaus)

## License


This project is licensed under the GPL v3 license - see the [LICENSE](LICENSE) file for details

