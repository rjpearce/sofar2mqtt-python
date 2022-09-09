# sofar-mqtt


# Sofar2MQTT

This project provides an integration between Sofar inverters over RS485 and MQTT.

## Setup


```bash
sudo apt-get install python-pip
sudo pip install -r requirements.txt
sudo cp systemd/sofar2mqtt.service /lib/systemd/system
sudo chmod 644 /lib/systemd/system/sofar2mqtt.service
sudo systemctl daemon-reload
sudo systemctl enable sofar2mqtt
sudo systemctl start sofar2mqtt
```


