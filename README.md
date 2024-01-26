# Sofar2MQTT - Python

## Overview

This project provides an integration between Sofar inverters over RS485 and MQTT using Python

It allows you to read and write data to Sofar inverters using a prebuilt Docker image or Python script. 

[View the documentation](https://github.com/rjpearce/sofar2mqtt-python/wiki)

## Inverter Compatability

This software is currently compatible with:

* Sofar ME3000
* Sofar HYD 3~6 EP

**Note:** It has only been tested on EP inverters.

There is no reason it cannot work with other Sofar inverters, the code and data have been seperately deliberately to support this you just need to provide the correct registers, see the following files:
* [sofar-hyd-ep.json](sofar-hyd-ep.json)
* [sofar-me-3000.json](sofar-me-3000.json)

Please do feel free to contribute changes and improvements.

### Example usage

[![Watch the video](img/ha-integration.png)](img/ha-integration.webm)
[Click here to watch the video](img/ha-integration.webm)

NOTE: The slightly weird behaviour of desired power when in `Self use`, it is probably best to only change it when you are in `Passive mode`.


## Known Issues

1. The desired_power control in Home Assistant does not update based on the actual setting in the inverter.
The inverter always returns 0 and I don't know why.
2. There are other modbus addresses that should be writable eg. Time of use SOC but they are not. I need to follow up with Sofar support to find out why.

## Credits

Based on a script originally created by Matt Nichols in 2021.
Thank you to Andre Wagner to his example write python code.
Thank you everyone on the [Sofar Solar Inverter - Remote Control & Smart Home Integration](https://www.facebook.com/groups/2477195449252168) Facebook group.

## Support

You can ping me directly on here or the awesome [Sofar Solar Inverter - Remote Control & Smart Home Integration](https://www.facebook.com/groups/2477195449252168) Facebook group

## Other interesting projects

* [Sofar2Mqtt - Using an ESP32 device to read from the inverter and send to MQTT](https://github.com/cmcgerty/Sofar2mqtt)
* [M5Stack Core2 MQTT Solar Display - DIY Solar display to show MQTT data](https://gitlab.com/rjpearce/m5stack-core2-mqtt-solar-display)
