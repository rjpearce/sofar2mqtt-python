# sofar-mqtt


# Sofar2MQTT

This project provides an integration between Sofar inverters over RS485 and MQTT.
It required a RaspberryPi or some other nix device with USB ports that can run Python.

This is currently compatible with:

* Sofar ME3000
* HYD-EP inverters. 

Note: It has only been tested on EP inverters.

There is no reason it cannot work with other Sofar inverters, the code and data have been seperately deliberately to support this you just need to provide the correct registers, see the following files:
* sofar-hyd-ep.json 
* sofar-me-3000.json

Please do contribute changes and updates.

## Dependencies

You will need:
1. A Raspberry Pi or similar with a *nix based operating system with Python 3 and pip installed
1. A USB to RS485 adapter with 3 outputs (+/-/GND) connected to your inverter
1. An MQTT broker/server
1. Home Assistant (optional)

## Setup:

```bash
sudo apt-get install python-pip
sudo pip install -r requirements.txt
```

## Configuring persistent serial devices:

1. Identify your USB serial devices. See: https://inegm.medium.com/persistent-names-for-usb-serial-devices-in-linux-dev-ttyusbx-dev-custom-name-fd49b5db9af1
1. An example file is provided, see 99-usb-serial.rules
1. Copy the udev rules: `sudo cp 99-usb-serial.rules /etc/udev/rules.d/99-usb-serial.rules`

## Configuring Home Assistant

An example configuration file to configure Home Assistant can be found in the ha folder.

## Usage (daemon mode):

```bash
sudo cp systemd/sofar2mqtt.service /lib/systemd/system
sudo chmod 644 /lib/systemd/system/sofar2mqtt.service
sudo systemctl daemon-reload
sudo systemctl enable sofar2mqtt
sudo systemctl start sofar2mqtt
```

## Usage

```bash
Usage: sofar2mqtt-v2.py [OPTIONS]

Options:
  --config-file TEXT          Configuration file to use  [required]
  --daemon                    Run as a daemon
  --retry INTEGER             Number of retries per register before giving up
  --retry-delay FLOAT         Delay before retrying
  --refresh-interval INTEGER  Refresh every n seconds
  --broker TEXT               MQTT broker address  [required]
  --topic TEXT                MQTT topic  [required]
  --log-level TEXT
  --device TEXT               [required]
  --help                      Show this message and exit
```

## Support

You can ping me directly on here or the awesome [Sofar Solar Inverter - Remote Control & Smart Home Integration](https://www.facebook.com/groups/2477195449252168) Facebook group

