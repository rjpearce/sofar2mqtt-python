#!/usr/bin/python3
""" Sofar 2 MQQT """
import datetime
import json
import time
import signal
import socket
import logging
import threading
import click
import traceback
import minimalmodbus
import serial
import struct
from multiprocessing import Process
import paho.mqtt.client as mqtt
import requests

VERSION = "3.1.0"

def load_config(config_file_path):
    """ Load configuration file """
    config = {}
    with open(config_file_path, mode='r', encoding='utf-8') as config_file:
        config = json.loads(config_file.read())
    return config

# pylint: disable=too-many-instance-attributes
class Sofar():
    """ Sofar """

    # pylint: disable=line-too-long,too-many-arguments
    def __init__(self, daemon, retry, retry_delay, write_retry, write_retry_delay, refresh_interval, broker, port, username, password, ca_certs, topic, write_topic, log_level, device, legacy_publish):
        self.daemon = daemon
        self.retry = retry
        self.retry_delay = retry_delay
        self.write_retry = write_retry
        self.write_retry_delay = write_retry_delay
        self.refresh_interval = refresh_interval
        self.broker = broker
        self.port = port
        self.username = username
        self.password = password
        self.ca_certs = ca_certs
        self.topic = topic
        self.write_topic = write_topic
        self.requests = 0
        self.failures = 0
        self.failed = []
        self.retries = 0
        self.instrument = None
        self.device = device
        self.legacy_publish = legacy_publish
        self.data = {}
        self.log_level = logging.getLevelName(log_level)
        self.iteration = 0
        logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.getLevelName(log_level))
        self.mutex = threading.Lock()
        self.setup_instrument()
        self.data['serial_number'] = self.determine_serial_number()
        if not self.data['serial_number']:
            logging.error("Failed to determine serial number. Exiting")
            exit(1)
        self.data['model'] = self.determine_model()
        self.data['protocol'] = self.determine_modbus_protocol()

        if self.data.get('protocol') == "SOFAR-1-40KTL.json":
            logging.error("Unsupported protocol detected. Exiting")

        self.config = load_config(self.data.get('protocol'))
        self.write_registers = []
        untested = False
        for register in self.config['registers']:
            if "untested" in register:
                untested = register["untested"]
            if "write" in register:
                if register["write"] and not untested:
                    self.write_registers.append(register)

        logging.info(f"Starting sofar2mqtt-python for serial number: {self.data.get('serial_number')}")
        self.update_state()
        self.client = mqtt.Client(client_id=f"sofar2mqtt-{socket.gethostname()}", userdata=None, protocol=mqtt.MQTTv5, transport="tcp")
        self.setup_mqtt(logging)
        
    def on_connect(self, client, userdata, flags, rc, properties=None):
        logging.info("MQTT "+mqtt.connack_string(rc))
        if rc == 0:
            try:
                self.publish_mqtt_discovery_bridge()
                self.publish_mqtt_discovery()
                logging.info(f"Subscribing to homeassistant/status")
                client.subscribe(f"homeassistant/status", qos=0, options=None, properties=None)
                for register in self.write_registers:
                    logging.info(f"Subscribing to {self.write_topic}/{register['name']}")
                    client.subscribe(f"{self.write_topic}/{register['name']}", qos=0, options=None, properties=None)
                for block in self.config.get('write_register_blocks', []):
                    logging.info(f"Subscribing to {self.write_topic}/{block['name']}")
                    client.subscribe(f"{self.write_topic}/{block['name']}", qos=0, options=None, properties=None)
            except Exception:
                logging.info(traceback.format_exc())

    def on_disconnect(client, userdata, rc, properties=None):
        if rc != 0:
            logging.info("MQTT un-expected disconnect")

    def on_message(self, client, userdata, message, properties=None):
        if message.retain: 
           logging.info(f"Ignoring retained message on topic {message.topic}") 
           return
        found = False
        valid = False
        topic = message.topic
        payload = message.payload.decode("utf-8") 
        if topic == "homeassistant/status":
            logging.info(f"Received message for {topic}:{payload}")
            if payload == "online":
                self.publish_mqtt_discovery_bridge()
                self.publish_mqtt_discovery()
            return

        for register in self.write_registers:
            if register['name'] == topic.split('/')[-1]:
                found = True
                if 'function' in register:
                    if register['function'] == 'mode':
                        new_mode = False
                        for key in register['modes']:
                            if register['modes'][key] == payload:
                              new_mode = key
                        logging.info(f"Received a request for {register['name']} to set mode value to: {payload}({new_mode})")
                        if not new_mode:
                            logging.error(f"Received a request for {register['name']} but mode value: {payload} is not a known mode. Ignoring")
                        if register['name'] in self.data:
                            retry = self.write_retry
                            while retry > 0:
                                if self.data[register['name']] == payload:
                                    logging.info(f"Current value for {register['name']}={self.data[register['name']]} matches desired value: {payload}. Ignoring")
                                    retry = 0
                                else:
                                    logging.info(f"Current value for {register['name']}={self.data[register['name']]}, attempting to set it to: {payload}. Retries remaining: {retry}")
                                    self.write_register(register, int(new_mode))
                                    time.sleep(self.write_retry_delay)
                                    retry = retry - 1
                        else: 
                            logging.error(f"No current read value for {register['name']} skipping write operation. Please try again.")

                    elif register['function'] == 'int':
                        value = int(payload)
                        logging.info(f"Received a request for {register['name']} to set value to: {payload}({value})")
                        if value < register['min']:
                            logging.error(f"Received a request for {register['name']} but value: {value} is less than the min value: {register['min']}. Ignoring")
                        elif value > register['max']:
                            logging.error(f"Received a request for {register['name']} but value: {value} is more than the max value: {register['max']}. Ignoring")
                        else:
                            if register['name'] == 'desired_power':
                                 if 'energy_storage_mode' in self.data:
                                     if 'Passive mode' != self.data['energy_storage_mode']:
                                         logging.info(f"Received a request for {register['name']} but not not in Passive mode. Ignoring")
                                         continue
                            if register['name'] in self.data:
                                retry = self.write_retry
                                while retry > 0:
                                    if self.data[register['name']] == value:
                                        logging.info(f"Current value for {register['name']}={self.data[register['name']]} matches desired value: {value}. Ignoring")
                                        retry = 0
                                    else:
                                        logging.info(f"Current value for {register['name']}={self.data[register['name']]}, attempting to set it to {value}. Retries remaining: {retry}")
                                        self.write_register(register, value)
                                        time.sleep(self.write_retry_delay)
                                        retry = retry - 1
                            else: 
                                logging.error(f"No current read value for {register['name']} skipping write operation. Please try again.")

        if not found:
            for block in self.config.get('write_register_blocks', []):
                if block['name'] == topic.split('/')[-1]:
                    logging.info(f"Received a request to write block: {block['name']}")
                    self.write_register_block(block['name'])
                    return
            logging.error(f"Received a request to set an unknown register or block: {topic.split('/')[-1]} to {payload}")

    def setup_mqtt(self, logging):
        self.client.enable_logger(logger=logging)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        if self.username is not None and self.password is not None:
            self.client.username_pw_set(self.username, self.password)
            logging.info(f"MQTT connecting to broker {self.broker} port {self.port} with auth user {self.username}")
        else:
            logging.info(f"MQTT connecting to broker {self.broker} port {self.port} without auth")
        self.client.reconnect_delay_set(min_delay=1, max_delay=300)
        if self.port == 8883:
            self.client.tls_set(ca_certs=self.ca_certs)

        self.client.connect(self.broker, port=self.port, keepalive=60, bind_address="", bind_port=0, clean_start=mqtt.MQTT_CLEAN_START_FIRST_ONLY, properties=None)
        self.client.loop_start()

    def setup_instrument(self):
        with self.mutex:
            logging.debug(f'Setting up instrument {self.device}')
            self.instrument = minimalmodbus.Instrument(self.device, 1)
            self.instrument.serial.baudrate = 9600   # Baud
            self.instrument.serial.bytesize = 8
            self.instrument.serial.parity = serial.PARITY_NONE
            self.instrument.serial.stopbits = 1
            self.instrument.serial.timeout  = 0.2   # seconds
            self.instrument.close_port_after_each_call = True

    def update_state(self):
        for register in self.config['registers']:
            refresh = 1
            if 'refresh' in register:
                refresh = register['refresh'] 
            if (self.iteration % refresh) != 0:
                logging.debug(f"Skipping {register['name']}")
                continue
            value = None
            signed = False
            logging.debug('Reading %s', register['name'])
            if 'signed' in register:
                signed = register['signed']
            if 'aggregate' in register:
                value = 0
                for register_name in register['aggregate']:
                    if register_name in self.data:
                        if value == 0:
                            value = self.data[register_name]
                        else:
                            if register['agg_function'] == 'add':
                                value += self.data[register_name]
                            elif register['agg_function'] == 'subtract':
                                value -= self.data[register_name]
                            elif register['agg_function'] == 'avg':
                                value = int((value + self.data[register_name]) / 2)
                if 'invert' in register:
                    if register['invert']:
                        if value > 0:
                            value = -abs(value)
                        else:
                            value = abs(value)
            else:
                read_type = 'register'
                registers = 1
                if 'read_type' in register:
                    read_type = register['read_type']
                if 'registers' in register:
                    registers = register['registers']
                value = self.read_register(
                        int(register['register'], 16),
                        read_type,
                        signed,
                        registers
                )
            if value is None:
                continue
            else:
                # Inverter will return maximum 16-bit integer value when data not available (eg. grid usage when grid down)
                if value == 65535:
                    value = 0
                if 'min' in register:
                    if value < register['min']:
                        logging.error(f"Value for {register['name']}: {str(value)} is lower than min allowed value: {register['min']}. Ignoring value")
                        continue
                if 'max' in register:
                    if value > register['max']:
                        logging.error(f"Value for {register['name']}: {str(value)} is greater than max allowed value: {register['max']}. Ignoring value")
                        continue
                if 'function' in register:
                    if register['function'] == 'multiply':
                        value = value * register['factor']
                    elif register['function'] == 'divide':
                        value = value / register['factor']
                    elif register['function'] == 'mode':
                        try:
                            value = register['modes'][str(value)]
                        except KeyError:
                            logging.error(f"Unknown mode value for {register['name']} value: {str(value)}")
                    elif register['function'] == 'bit_field':
                        length = len(register['fields'])
                        fields = []
                        for n in reversed(range(length)):
                            if value & (1 << ((length-1)-n)):
                                fields.append(register['fields'][n])
                        value = (','.join(fields))
                    elif register['function'] == 'high_bit_low_bit':
                        high = value >> 8 # shift right 
                        low = value & 255 # apply bitmask 
                        value = f"{high:02}{register['join']}{low:02}" # combine and pad 2 zeros 
            logging.debug('Read %s:%s', register['name'], value)

            if not self.data.get(register.get('name')) == value:
                if register.get('notify_on_change', False):
                    logging.info(f"Notification - {register.get('name')} has changed to: {value}")
            self.data[register.get('name')] = value 
        failure_percentage = round(self.failures / (self.requests+self.retries)*100,2)
        retry_percentage = round(self.retries / (self.requests)*100,2)
        logging.info(f"Modbus Requests: {self.requests} Retries: {self.retries} ({retry_percentage}%) Failures: {self.failures} ({failure_percentage}%)")
        self.data['modbus_failures'] = self.failures
        self.data['modbus_requests'] = self.requests
        self.data['modbus_retries'] = self.retries
        self.data['modbus_failure_rate'] = failure_percentage
        self.data['modbus_retry_rate'] = retry_percentage

    def publish_state(self):
        try:
            data = json.dumps(self.data, indent=2)
            self.client.publish(self.topic + "state_all", data, retain=True)

            with open("data.json", "w") as write_file:
                write_file.write(data)
            if self.legacy_publish:
                self.publish_legacy_state()
        except Exception:
            logging.info(traceback.format_exc())
        time.sleep(self.refresh_interval)

    def publish_legacy_state(self):
        for register in self.config['registers']:
            logging.debug('Publishing %s:%s', self.topic + register.get("name"), self.data.get(register.get("name")))
            try:
                self.client.publish(self.topic + register.get("name"), self.data.get(register.get("name")), retain=False)
            except Exception:
                logging.debug(traceback.format_exc())

    def publish_mqtt_discovery_bridge(self):
        payload = {
            "device": {
               "identifiers": [f"sofar2mqtt_python_bridge_{self.data.get('serial_number')}"],
               "manufacturer": "Sofar2Mqtt-Python",
               "model": "Bridge",
               "name": "Sofar2Mqtt Python Bridge",
               "sw_version": VERSION
            },
            "device_class": "connectivity",
            "entity_category": "diagnostic",
            "name": "Connection state",
            "object_id": "sofar2mqtt_python_bridge_connection_state",
            "payload_off": "offline",
            "payload_on": "online",
            "state_topic": "sofar2mqtt_python/bridge",
            "unique_id": f"bridge_{self.data.get('serial_number')}_connection_state_sofar2mqtt_python",
        }
        topic = f"homeassistant/binary_sensor/{self.data.get('serial_number')}/connection_state/config"

        try:
            logging.info(f"Publishing bridge via MQTT to {topic}")
            self.client.publish(topic, json.dumps(payload), retain=False)
            self.client.publish("sofar2mqtt_python/bridge", "online", retain=False)
        except Exception:
            logging.info(traceback.format_exc())

    def publish_mqtt_discovery(self):
        logging.info(f"Publishing controls via MQTT")
        for register in self.config['registers']:
            if 'ha' not in register:
                continue
            try:
                default_payload = {
                    "name": register['name'],
                    "state_topic": "sofar/state_all",
                    "unique_id": f"{self.data.get('serial_number')}_{register['name']}",
                    "entity_id": f"sofar_{register['name']}",
                    "enabled_by_default": "true",
                    "device": {
                        "name": f"Sofar",
                        "sw_version": self.data.get("sw_version_com"),
                        "hw_version": self.data.get("hw_version"),
                        "manufacturer": "Sofar",
                        "model": self.data.get('model'),
                        "configuration_url": "https://github.com/rjpearce/sofar2mqtt-python",
                        "identifiers": [f"{self.data.get('serial_number')}"]
                    },
                    "availability": [
                        {
                            "topic": "sofar2mqtt_python/bridge",
                            "value": "online"
                       }
                    ],
                }
                payload = default_payload | register['ha']
                control = 'sensor'
                if 'control' in register['ha']:
                    control = register['ha']['control']
                topic = f"homeassistant/{control}/sofar_{register['name']}/config"
                self.client.publish(topic, json.dumps(payload), retain=False)
            except Exception:
                logging.info(traceback.format_exc())

    def signal_handler(self, sig, _frame):
      logging.info(f"Received signal {sig}, attempting to stop")
      self.daemon = False

    def terminate(self):
      logging.info("Terminating")
      logging.info(f"Publishing offline to sofar2mqtt_python/bridge")
      self.client.publish("sofar2mqtt_python/bridge", "offline", retain=False)
      self.client.loop_stop()
      exit(0)

    def main(self):
        """ Main method """
        signal.signal(signal.SIGTERM, self.signal_handler)
        signal.signal(signal.SIGINT, self.signal_handler)
        if not self.daemon:
            self.update_state()
            self.publish_state()
        while (self.daemon):
            now = datetime.datetime.now()
            """ Sleep for 34 seconds to allow the inverter to reset the stats at 00:00 """
            if (now.hour == 22 and now.minute == 59 and now.second >= 30):
                logging.info('Snoozing 34 seconds')
                time.sleep(34)
            self.requests = 0
            self.failures = 0
            self.failed = []
            self.retries = 0
            self.update_state()
            self.publish_state()
            time.sleep(self.refresh_interval)
            self.iteration+=1
        self.terminate()

    def write_register(self, register, value):
        """ Read value from register with a retry mechanism """
        with self.mutex:
            retry = self.write_retry
            logging.info(f"Writing {register['register']}({int(register['register'], 16)}) with {value}({value})")
            signed = False
            success = False
            retries = 0
            failed = 0 
            if 'signed' in register:
                signed = register['signed']
            while retry > 0 and not success:
                try:
                    if register['type'] == 'U16':
                        self.instrument.write_register(int(register['register'],16), int(value))
                    elif register['type'] == 'I32':
                        # split the value to a byte
                        values = struct.pack(">l", value)
                        # split low and high byte
                        low = struct.unpack(">H", bytearray([values[0], values[1]]))[0]
                        high = struct.unpack(">H", bytearray([values[2], values[3]]))[0]
                        # send the registers
                        self.instrument.write_registers(int(register['register'],16), [0, 0, low, high, low, high])
                except minimalmodbus.NoResponseError:
                    logging.debug(f"Failed to write_register {register['name']} {traceback.format_exc()}")
                    retry = retry - 1
                    retries = retries + 1
                    time.sleep(self.write_retry_delay)
                except minimalmodbus.InvalidResponseError:
                    logging.debug(f"Failed to write_register {register['name']} {traceback.format_exc()}")
                    retry = retry - 1
                    retries = retries + 1
                    time.sleep(self.write_retry_delay)
                except serial.serialutil.SerialException:
                    logging.debug(f"Failed to write_register {register['name']} {traceback.format_exc()}")
                    retry = retry - 1
                    retries = retries + 1
                    time.sleep(self.write_retry_delay)
                success = True
            if success:
                logging.info('Modbus Write Request: %s successful. Retries: %d', register['name'], retries)
            else:
                logging.error('Modbus Write Request: %s failed. Retry exhausted. Retries: %d', register['name'], retries)

    def read_register(self, registeraddress, read_type, signed, registers=1):
        """ Read value from register with a retry mechanism """
        with self.mutex:
            value = None
            retry = self.retry
            while retry > 0 and value is None:
                try:
                    self.requests +=1
                    if read_type == "register":
                        value = self.instrument.read_register(
                            registeraddress, 0, functioncode=3, signed=signed)
                    elif read_type == "long":
                        value = self.instrument.read_long(
                            registeraddress, functioncode=3, signed=True, number_of_registers=2)
                    elif read_type == "string":
                        value = self.instrument.read_string(
                            registeraddress, functioncode=3, number_of_registers=registers)
                except minimalmodbus.NoResponseError:
                    logging.debug(traceback.format_exc())
                    retry = retry - 1
                    self.retries = self.retries + 1
                    time.sleep(self.retry_delay)
                except minimalmodbus.InvalidResponseError:
                    logging.debug(traceback.format_exc())
                    retry = retry - 1
                    self.retries = self.retries + 1
                    time.sleep(self.retry_delay)
                except serial.serialutil.SerialException:
                    logging.debug(traceback.format_exc())
                    retry = retry - 1
                    self.retries = self.retries + 1
                    time.sleep(self.retry_delay)

            if retry == 0:
                self.failures = self.failures + 1
                self.failed.append(registeraddress)
            return value

    def determine_serial_number(self):
        """ Determine the serial number from the inverter """
        serial_number = None

        # Try first location: 0x2001 ... 0x2007
        try:
            serial_number = ''.join([self.read_register(register, 'string', False, 1) for register in range(0x2001, 0x2008)])
            if serial_number:
                logging.info(f"Serial number found at first location: {serial_number}")
                return serial_number
        except Exception:
            logging.debug("Failed to read serial number from first location")

        # Try second location: 0x0445 ... 0x044B (14 digits)
        try:
            serial_number = ''.join([self.read_register(register, 'string', False, 1) for register in range(0x0445, 0x044C)])
            if serial_number:
                logging.info(f"Serial number found at second location: {serial_number}")
                return serial_number
        except Exception:
            logging.debug("Failed to read serial number from second location")

        # Try third location: 0x0445 ... 0x044C and 0x0470...0x0471 (20 digits)
        try:
            serial_number_part1 = ''.join([self.read_register(register, 'string', False, 1) for register in range(0x0445, 0x044C)])
            serial_number_part2 = ''.join([self.read_register(register, 'string', False, 1) for register in range(0x0470, 0x0472)])
            if serial_number_part2 and int(serial_number_part2) != 0:
                serial_number = serial_number_part1 + serial_number_part2
                logging.info(f"Serial number found at third location: {serial_number}")
                return serial_number
            elif serial_number_part1:
                logging.info(f"Serial number found at second location (fallback): {serial_number_part1}")
                return serial_number_part1
        except Exception:
            logging.debug("Failed to read serial number from third location")

        logging.error("Failed to determine serial number")
        return None

    def determine_model(self):
        """ Determine the model of the inverter based on the serial number """
        serial_number = self.data.get('serial_number')
        model = None
        if len(serial_number) == 14:
            code = serial_number[1:3]
            model_mapping = {
                "A1": "SOFAR 1000...3000TL",
                "A3": "SOFAR 1100...3300TL-G3",
                "B1": "SOFAR 3...6KTLM",
                "C1": "SOFAR 10...20KTL",
                "C2": "SOFAR 10...20KTL",
                "C3": "SOFAR 10...20KTL",
                "C4": "SOFAR 10...20KTL",
                "D1": "SOFAR 10...20KTL",
                "D2": "SOFAR 10...20KTL",
                "D3": "SOFAR 10...20KTL",
                "D4": "SOFAR 10...20KTL",
                "E1": "SOFAR ME 3000-SP",
                "F1": "SOFAR 3.3...12KTL-X",
                "F2": "SOFAR 3.3...12KTL-X",
                "F3": "SOFAR 3.3...12KTL-X",
                "F4": "SOFAR 3.3...12KTL-X",
                "G1": "SOFAR 30...40KTL-G2",
                "G2": "SOFAR 30...40KTL-G2",
                "H1": "SOFAR 3...6KTLM-G2",
                "H3": "SOFAR 3...6KTLM-G3",
                "H4": "SOFAR 7.5KTLM-G3",
                "I1": "SOFAR 50...70KTL",
                "J1": "SOFAR 50...70KTL-G2",
                "J2": "SOFAR 50...70KTL-G2",
                "J3": "SOFAR 50...70KTL-G2",
                "K1": "SOFAR 7.5KTLM",
                "L1": "SOFAR 20...33KTL-G2",
                "M1": "SOFAR HYD 3000...6000-ES",
                "M2": "SOFAR HYD 3000...6000-EP",
                "N1": "SOFAR 10...15KTL-G2",
                "P1": "SOFAR HYD 5...20KTL-3PH",
                "P2": "SOFAR HYD 5...20KTL-3PH",
                "Q1": "SOFAR 75...136KTL",
                "R1": "SOFAR 255KTL-HV",
                "S1": "SOFAR 15...24KTLX-G3",
                "S2": "SOFAR 3.3...12KTLX-G3",
                "S3": "SOFAR 25...50KTLX-G3",
                "S4": "SOFAR 60...80KTLX-G3",
                "T1": "SOFAR 7...10.5KTLM-G3",
                "U1": "SOFAR ME 5...20KTL-3PH",
                "U2": "SOFAR ME 5...20KTL-3PH",
                "U3": "SOFAR ME 5...20KTL-3PH"
            }
            model = model_mapping.get(code)
        elif len(serial_number) == 20:
            code = serial_number[2:6]
            model_mapping = {
                "1012": "SOFAR 1100...3300TL-G3",
                "1005": "SOFAR ME 3000-SP",
                "1012": "SOFAR 3..6KTLM-G3",
                "1018": "SOFAR 7.5KTLM-G3",
                "1005": "SOFAR HYD 3000..6000-EP",
                "1033": "SOFAR HYD 5..20KTL-3PH",
                "1017": "SOFAR 255KTL-HV",
                "1016": "SOFAR 3.3..24KTLX-G3",
                "1021": "SOFAR 60...80KTLX-G3",
                "1036": "SOFAR 100...125KTLX-G4",
                "1018": "SOFAR 7...10.5KTLM-G3",
                "1019": "SOFAR ME 5...20KTL-3PH",
                "1025": "SOFAR ESI 2.5...5.0K"
            }
            model = model_mapping.get(code)

        if model:
            logging.info(f"Model determined: {model}")
        else:
            logging.error("Failed to determine model from serial number")
        return model

    def determine_modbus_protocol(self):
        """ Determine the Modbus protocol based on the model """

        protocol_mapping = {
            "SOFAR 1000...3000TL": "SOFAR-1-40KTL.json",
            "SOFAR 1100...3300TL-G3": "SOFAR-1-40KTL.json",
            "SOFAR 3...6KTLM": "SOFAR-1-40KTL.json",
            "SOFAR 10...20KTL": "SOFAR-1-40KTL.json",
            "SOFAR ME 3000-SP": "SOFAR-HYD-ES-AND-ME3000-SP.json",
            "SOFAR 3.3...12KTL-X": "SOFAR-1-40KTL.json",
            "SOFAR 30...40KTL-G2": "SOFAR-1-40KTL.json",
            "SOFAR 3...6KTLM-G2": "SOFAR-1-40KTL.json",
            "SOFAR 7.5KTLM": "SOFAR-1-40KTL.json",
            "SOFAR 20...33KTL-G2": "SOFAR-1-40KTL.json",
            "SOFAR 10...15KTL-G2": "SOFAR-1-40KTL.json",
            "SOFAR HYD 3000...6000-ES": "SOFAR-HYD-ES-AND-ME3000-SP.json",
            "SOFAR HYD 3000...6000-EP": "SOFAR-HYD-3PH-AND-G3.json",
            "SOFAR HYD 5...20KTL-3PH": "SOFAR-HYD-3PH-AND-G3.json",
            "SOFAR 75...136KTL": "SOFAR-HYD-3PH-AND-G3.json",
            "SOFAR 255KTL-HV": "SOFAR-HYD-3PH-AND-G3.json",
            "SOFAR 15...24KTLX-G3": "SOFAR-HYD-3PH-AND-G3.json",
            "SOFAR 3.3...12KTLX-G3": "SOFAR-HYD-3PH-AND-G3.json",
            "SOFAR 25...50KTLX-G3": "SOFAR-HYD-3PH-AND-G3.json",
            "SOFAR 60...80KTLX-G3": "SOFAR-HYD-3PH-AND-G3.json",
            "SOFAR 7...10.5KTLM-G3": "SOFAR-HYD-3PH-AND-G3.json",
            "SOFAR ME 5...20KTL-3PH": "SOFAR-HYD-3PH-AND-G3.json",
            "SOFAR ESI 2.5...5.0K": "SOFAR-HYD-3PH-AND-G3.json"
        }

        modbus_protocol = protocol_mapping.get(self.data.get('model'))
        if modbus_protocol:
            logging.info(f"Modbus protocol determined: {modbus_protocol}")
        else:
            logging.error("Failed to determine Modbus protocol from model")
        return modbus_protocol

    def convert_value(self, register_name, value):
        """
        Convert value based on register modes.

        Examples:
        - If the register has modes defined as:
          {
              "0": "Default",
              "1": "Pylon",
              "2": "General"
          }
          and the value is "Pylon", it will return "1".
        - If the value does not match any mode, it will return the original value.

        Args:
            register_name (str): The name of the register.
            value (str): The value to be converted.

        Returns:
            str: The converted value or the original value if no conversion is needed.
        """
        register = next((r for r in self.config['registers'] if r['name'] == register_name), None)
        if register and 'modes' in register:
            value = next((k for k, v in register['modes'].items() if v == value), value)
        return value

    def write_register_block(self, block_name):
        """ Write a specific register block from configuration to Modbus """
        block = next((b for b in self.config.get('write_register_blocks', []) if b['name'] == block_name), None)
        if not block:
            logging.error(f"Block {block_name} not found in configuration")
            return

        logging.info(f"Block: {block}")
        start_register = int(block['start_register'], 16)
        length = int(block['length'])
        values = []
        for register_name in block['registers']:
            value = self.data.get(register_name)
            if value is None:
                logging.error(f"Value for {register_name} not found in data. Skipping block {block['name']}")
                return
            value = int(self.convert_value(register_name, value))
            values.append(value)
        try:
            #self.instrument.write_registers(start_register, values[:length])
            logging.info(f"Would write {start_register} with {values[:length]}")
            logging.info(f"Successfully wrote block {block['name']} to Modbus")
        except Exception as e:
            logging.error(f"Failed to write block {block['name']} to Modbus: {str(e)}")


@click.command("cli", context_settings={'show_default': True})
@click.option(
    '--daemon',
    envvar='DAEMON',
    is_flag=True,
    default=False,
    help='Run as a daemon',
)
@click.option(
    '--retry',
    envvar='RETRY_ATTEMPT',
    default=2,
    type=int,
    help='Number of read retries per register before giving up',
)
@click.option(
    '--retry-delay',
    envvar='RETRY_DELAY',
    default=0.1,
    type=float,
    help='Delay before retrying read',
)
@click.option(
    '--write-retry',
    envvar='WRITE_RETRY_ATTEMPTS',
    default=5,
    type=int,
    help='Number of write retries per register before giving up',
)
@click.option(
    '--write-retry-delay',
    envvar='WRITE_RETRY_DELAY',
    default=5,
    type=int,
    help='Delay before retrying write',
)
@click.option(
    '--refresh-interval',
    envvar='REFRESH_INTERVAL',
    default=0,
    type=int,
    help='Refresh data every n seconds',
)
@click.option(
    '--broker',
    envvar='MQTT_HOST',
    default='localhost',
    help='MQTT broker address',
)
@click.option(
    '--port',
    envvar='MQTT_PORT',
    default=1883,
    type=int,
    help='MQTT broker port',
)
@click.option(
    '--username',
    envvar='MQTT_USERNAME',
    default=None,
    help='MQTT username'
)
@click.option(
    '--password',
    envvar='MQTT_PASSWORD',
    default=None,
    help='MQTT password'
)
@click.option(
    '--ca-certs',
    envvar='MQTT_CA_CERTS',
    default=None,
    help='MQTT CA Certs path'
)
@click.option(
    '--topic',
    envvar='MQTT_TOPIC',
    default='sofar/',
    help='MQTT topic for reading',
)
@click.option(
    '--write-topic',
    envvar='MQTT_WRITE_TOPIC',
    default='sofar/rw',
    help='MQTT topic for writing',
)
@click.option(
    '--log-level',
    envvar='LOG_LEVEL',
    default='INFO',
    type=click.Choice(['INFO', 'DEBUG'], case_sensitive=False),
    help='Log Level'
)
@click.option(
    '--device',
    envvar='TTY_DEVICE',
    default='/dev/ttyUSB0',
    help='RS485/USB Device'
)
@click.option(
    '--legacy-publish',
    envvar='LEGACY_PUBLISH',
    default=True,
    help='Publish each register to MQTT individually in addition to state which contains all values',
)
# pylint: disable=too-many-arguments
def main(daemon, retry, retry_delay, write_retry, write_retry_delay, refresh_interval, broker, port, username, password, ca_certs, topic, write_topic, log_level, device, legacy_publish):
    """Main"""
    sofar = Sofar(daemon, retry, retry_delay, write_retry, write_retry_delay, refresh_interval, broker, port, username, password, ca_certs, topic, write_topic, log_level, device, legacy_publish)
    sofar.main()

# pylint: disable=no-value-for-parameter
if __name__ == '__main__':
    main()
