# Sofar2MQTT - Python

[![Build Docker Image](https://github.com/rjpearce/sofar2mqtt-python/actions/workflows/docker-image.yml/badge.svg)](https://github.com/rjpearce/sofar2mqtt-python/actions/workflows/docker-image.yml)

## Overview

This project provides an integration between Sofar inverters over RS485 and MQTT using Python

It allows you to read and write data to Sofar inverters using a prebuilt Docker image (preferred) or Python script . 

[View the documentation](https://github.com/rjpearce/sofar2mqtt-python/wiki)

## Release notes

### 3.0.1

* Implemented MQTT auto discovery for home assistant - no more manual config!
* Added a new refresh option for each register allowing some registers to be read more regularly (fresher) than other that are less important (i.e serial number)
* Added registers for serial number, software version, hardware version.
* The script now retains a local dict of data which is updated after reading registers for this iteration (based on refresh)
* After an iteration the entire dict (JSON) is sent to a new topic sofar/state_all'
* Added a new option for LEGACY_PUBLISH to continue to send messages individually in addition to sofar/state_all.
* Introduce Signal handling to ensure graceful exit

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

### Home Assistant auto-discovery

The gateway supports Home Assistant MQTT discovery. It publishes configuration information automatically, the inverter will appears as an new MQTT device. No more manual configuration in Home Assistant!

## Credits

Based on a script originally created by Matt Nichols in 2021.
Thank you to Andre Wagner to his example write python code.
Thank you everyone on the [Sofar Solar Inverter - Remote Control & Smart Home Integration](https://www.facebook.com/groups/2477195449252168) Facebook group.

## Support

You can ping me directly on here or the awesome [Sofar Solar Inverter - Remote Control & Smart Home Integration](https://www.facebook.com/groups/2477195449252168) Facebook group

## Other interesting projects

* [Sofar2Mqtt - Using an ESP32 device to read from the inverter and send to MQTT](https://github.com/cmcgerty/Sofar2mqtt)
* [M5Stack Core2 MQTT Solar Display - DIY Solar display to show MQTT data](https://gitlab.com/rjpearce/m5stack-core2-mqtt-solar-display)
