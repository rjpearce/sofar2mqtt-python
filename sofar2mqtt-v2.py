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
import os

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
        self.failure_pattern = ""
        self.retries = 0
        self.instrument = None
        self.device = device
        self.legacy_publish = legacy_publish
        self.raw_data = {}
        self.log_level = logging.getLevelName(log_level)
        self.iteration = 0
        logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s',
                            level=logging.getLevelName(log_level))
        logging.info(f"Starting sofar2mqtt-python {VERSION}")
        self.mutex = threading.Lock()
        self.setup_instrument()
        self.client = mqtt.Client(
            client_id=f"sofar2mqtt-{socket.gethostname()}", userdata=None, protocol=mqtt.MQTTv5, transport="tcp")
        if os.environ.get("DEVICE_TYPE"):
            protocol_file = os.environ.get("DEVICE_TYPE") + ".json"
        else:
            self.raw_data['serial_number'] = self.determine_serial_number()
            if not self.raw_data['serial_number']:
                logging.error("Failed to determine serial number, Exiting")
                self.terminate(status_code=1)
            self.raw_data['model'] = self.determine_model()
            self.raw_data['protocol'] = self.determine_modbus_protocol()
            protocol_file = self.raw_data.get('protocol', False)

            if protocol_file == "SOFAR-1-40KTL.json":
                logging.error(f"Sorry {self.raw_data['model']} is not currently supported. Exiting")
                self.terminate(status_code=1)
            if not protocol_file:
                logging.error(f"Unknown protocol for model: {self.raw_data['model']}. Exiting")
                self.terminate(status_code=1)
            if not os.path.isfile(protocol_file):
                logging.error(
                    f"Protocol file {protocol_file} does not exist. Exiting")
                self.terminate(status_code=1)

        self.config = load_config(protocol_file)

        if 'registers' in self.config:
            if 'serial_number' in self.config['registers']:
                serial_number = self.config['registers']['serial_number']['value']
                logging.error(f"Using static serial number from config file. Serial Number: {serial_number}")
                self.raw_data['serial_number'] = serial_number

        self.write_registers = []
        untested = False
        for register in self.config['registers']:
            if "untested" in register:
                untested = register["untested"]
            if "write" in register:
                if register["write"] and not untested:
                    self.write_registers.append(register)

        logging.info(
            f"Starting sofar2mqtt-python for serial number: {self.raw_data.get('serial_number')}")
        self.setup_mqtt(logging)
        self.update_state()

    def on_connect(self, client, userdata, flags, rc, properties=None):
        logging.info("MQTT "+mqtt.connack_string(rc))
        if rc == 0:
            try:
                self.publish_mqtt_discovery_bridge()
                self.publish_mqtt_discovery()
                logging.info(f"Subscribing to homeassistant/status")
                client.subscribe(f"homeassistant/status", qos=0,
                                 options=None, properties=None)
                for register in self.write_registers:
                    logging.info(
                        f"Subscribing to {self.write_topic}/{register['name']}")
                    client.subscribe(
                        f"{self.write_topic}/{register['name']}", qos=0, options=None, properties=None)
                for block in self.config.get('write_register_blocks', []):
                    logging.info(
                        f"Subscribing to {self.write_topic}/{block['name']}")
                    client.subscribe(
                        f"{self.write_topic}/{block['name']}/#", qos=0, options=None, properties=None)
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
                new_raw_value = self.translate_to_raw_value(register, payload)
                found = True
                if 'function' not in register:
                    logging.error(f"No function was provided for register {register['name']} skipping write operation. Check the JSON is configured correctly.")
                    continue
                if register['function'] == 'mode':
                    new_value = register['modes'].get(
                        str(new_raw_value), None)
                    logging.info(
                        f"Received a request for {register['name']} to set mode value to: {new_raw_value} ({new_value})")
                    if not new_value:
                        logging.error(
                            f"Received a request for {register['name']} but mode value: {new_value} is not a known mode. Ignoring")
                    if register['name'] in self.raw_data:
                        retry = self.write_retry
                        raw_value = self.raw_data.get(
                            register.get('name'), None)
                        value = self.translate_from_raw_value(
                            register, raw_value)
                        while retry > 0:
                            if self.raw_data[register['name']] == int(new_raw_value):
                                logging.info(
                                    f"Current value for {register['name']}: {raw_value} ({value}). Matches desired value: {new_raw_value} ({new_value}).")
                                retry = 0
                            else:
                                logging.info(
                                    f"Current value for {register['name']}: {raw_value} ({value}), attempting to set it to: {new_raw_value} ({new_value}). Retries remaining: {retry}")
                                self.write_register(
                                    register, int(new_raw_value))
                                time.sleep(self.write_retry_delay)
                                retry = retry - 1
                    else:
                        logging.error(
                            f"No current read value for {register['name']} skipping write operation. Please try again.")
                else:
                    logging.info(
                        f"Received a request for {register['name']} to set value to: {payload}({new_raw_value})")
                    if int(new_raw_value) < register['min']:
                        logging.error(
                            f"Received a request for {register['name']} but value: {new_raw_value} is less than the min value: {register['min']}. Ignoring")
                    elif int(new_raw_value) > register['max']:
                        logging.error(
                            f"Received a request for {register['name']} but value: {new_raw_value} is more than the max value: {register['max']}. Ignoring")
                    else:
                        if register['name'] == 'desired_power':
                            if int(self.raw_data.get('energy_storage_mode', None)) == 0:
                                logging.info(
                                    f"Received a request for {register['name']} but energy_storage_mode is not in Passive mode. Ignoring")
                                continue
                        if register['name'] == 'charge_discharge_power':
                            if int(self.raw_data.get('working_mode', None)) != 3:
                                logging.info(
                                    f"Received a request for {register['name']} but working_mode is not in Passive mode. Ignoring")
                                continue
                        if 'write_addresses' in register:
                            write_register = None
                            write_functioncode = register.get('write_functioncode', '16')
                            if new_raw_value == 0:
                                write_register = register['write_addresses'].get("standby", None)
                                new_raw_value = register['write_values'].get("standby", new_raw_value)
                            elif new_raw_value < 0:
                                write_register = register['write_addresses'].get("discharge", None)
                            elif new_raw_value > 0:
                                write_register = register['write_addresses'].get("charge", None)
                            if write_register is None:
                                logging.error(
                                    f"No write address found for value: {new_raw_value} on register: {register['name']}. Ignoring")
                                continue
                            logging.info(
                                f"Mapping value: {new_raw_value} to write register: {write_register} for register: {register['name']}")
                            self.write_register_special(write_register, write_functioncode, abs(new_raw_value))
                            continue
                        if register['name'] in self.raw_data:
                            retry = self.write_retry
                            while retry > 0:
                                if int(self.raw_data[register['name']]) == int(new_raw_value):
                                    logging.info(
                                        f"Current value for {register['name']}: {self.raw_data[register['name']]} matches desired value: {new_raw_value}")
                                    retry = 0
                                else:
                                    logging.info(
                                        f"Current value for {register['name']}: {self.raw_data[register['name']]}, attempting to set it to {new_raw_value}. Retries remaining: {retry}")
                                    self.write_register(
                                        register, int(new_raw_value))
                                    time.sleep(self.write_retry_delay)
                                    retry = retry - 1
                        else:
                            logging.error(
                                f"No current read value for {register['name']} skipping write operation. Please try again.")

        if not found:
            for block in self.config.get('write_register_blocks', []):
                if block['name'] == topic.split('/')[-2]:
                    update_register = topic.split('/')[-1]
                    logging.info(
                        f"Received a request to write block: {topic} {block['name']}_{update_register} {payload}")
                    self.write_register_block(
                        block['name'], f"{block['name']}_{update_register}", payload)
                    return
            logging.error(
                f"Received a request to set an unknown register or block: {topic} to {payload}")

    def setup_mqtt(self, logging):
        self.client.enable_logger(logger=logging)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        if self.username is not None and self.password is not None:
            self.client.username_pw_set(self.username, self.password)
            logging.info(
                f"MQTT connecting to broker {self.broker} port {self.port} with auth user {self.username}")
        else:
            logging.info(
                f"MQTT connecting to broker {self.broker} port {self.port} without auth")
        self.client.reconnect_delay_set(min_delay=1, max_delay=300)
        if self.port == 8883:
            self.client.tls_set(ca_certs=self.ca_certs)

        self.client.connect(self.broker, port=self.port, keepalive=60, bind_address="",
                            bind_port=0, clean_start=mqtt.MQTT_CLEAN_START_FIRST_ONLY, properties=None)
        self.client.loop_start()

    def setup_instrument(self):
        with self.mutex:
            logging.debug(f'Setting up instrument {self.device}')
            self.instrument = minimalmodbus.Instrument(self.device, 1)
            self.instrument.serial.baudrate = 9600   # Baud
            self.instrument.serial.bytesize = 8
            self.instrument.serial.parity = serial.PARITY_NONE
            self.instrument.serial.stopbits = 1
            self.instrument.serial.timeout = 0.5   # seconds
            self.instrument.close_port_after_each_call = False
            self.instrument.clear_buffers_before_each_transaction = True

    def aggregate_datetime_bitmap(self, register):
        additional_registers = register.get('aggregate_datetime_bitmap', {})
        ts = self.read_event_timestamp(
            additional_registers.get("year_month",""),
            additional_registers.get("day_hour",""),
            additional_registers.get("minute_second","")
        )
        if ts is None: 
            return "No valid timestamp available"
        else: 
            return ts.strftime("%Y-%m-%d %H:%M:%S")

    def combine_aggregate_registers(self, register):
        """ Combine registers from the 'aggregate' field using the arithmetic function in 'agg_function' """
        raw_value = 0
        for agg_register_name in register['aggregate']:
            if agg_register_name in self.raw_data:
                if raw_value == 0:
                    raw_value = self.raw_data[agg_register_name]
                else:
                    if register['agg_function'] == 'add':
                        raw_value += self.raw_data[agg_register_name]
                    elif register['agg_function'] == 'subtract':
                        raw_value -= self.raw_data[agg_register_name]
                    elif register['agg_function'] == 'avg':
                        raw_value = int(
                            (raw_value + self.raw_data[agg_register_name]) / 2)
        self.raw_data[register['name']] = raw_value
        return raw_value

    def update_state(self):
        for register in self.config['registers']:
            if not register.get('read', True):
                continue
            refresh = register.get('refresh', 1)
            if (self.iteration % refresh) != 0:
                logging.debug(f"Skipping {register['name']}")
                continue
            raw_value = None
            logging.debug('Reading %s', register['name'])
           
            if register.get('read_type') == 'static':
                logging.info(f"Using static value for {register['name']}")
                raw_value = register['value']
            if 'aggregate' in register:
                raw_value = self.combine_aggregate_registers(register)
            if register.get('register', False):
                if register.get('read', True):
                    raw_value = self.read_register(
                        int(register['register'], 16),
                        register.get('read_type', 'register'),
                        register.get('signed', False),
                        register.get('registers', 1)
                    )

            if 'aggregate_datetime_bitmap' in register:
                continue
                #raw_value =  self.aggregate_datetime_bitmap(register)
            if raw_value is None:
                logging.error(f"Value for {register['name']}: is none")
                continue
            else:
                # Normalize inverter 'no data' sentinel values before translation
                if isinstance(raw_value, int) and (raw_value == 65535 or raw_value == -1):
                    logging.debug(f"Raw sentinel value for {register['name']} detected: {raw_value}; normalizing to 0")
                    raw_value = 0
                value = self.translate_from_raw_value(register, raw_value)
                # Inverter will return maximum 16-bit integer value when data not available (eg. grid usage when grid down)
                if value == 65535:
                    value = 0
                if 'min' in register:
                    if int(value) < register.get('min'):
                        logging.error(
                            f"Value for {register['name']}: {str(value)} is lower than min allowed value: {register['min']}")
                if 'max' in register:
                    if int(value) > register.get('max', 0):
                        logging.error(
                            f"Value for {register['name']}: {str(raw_value)} is greater than max allowed value: {register['max']}")
                logging.debug(f"Read {register['name']} {value}")

            if not self.raw_data.get(register.get('name')) == raw_value:
                if register.get('notify_on_change', False):
                    from_raw = self.raw_data.get(register.get('name'))
                    try:
                        from_value = self.translate_from_raw_value(
                            register, from_raw)
                    except (ValueError, TypeError) as e:
                        logging.error(f"Conversion failed for {register['name']}, value {from_raw}: {e}")
                        continue
                    logging.info(
                        f"Notification - {register.get('name')} has changed from: {from_raw} ({from_value}) to: {raw_value} ({value})")
                self.raw_data[register.get('name')] = raw_value
        failure_percentage = round(
            self.failures / (self.requests+self.retries)*100, 2)
        retry_percentage = round(self.retries / (self.requests)*100, 2)
        logging.info(
            f"Modbus Requests: {self.requests} Retries: {self.retries} ({retry_percentage}%) Failures: {self.failures} ({failure_percentage}%)")
        logging.info(self.failure_pattern)
        self.failure_pattern = ""
        self.raw_data['modbus_failures'] = self.failures
        self.raw_data['modbus_requests'] = self.requests
        self.raw_data['modbus_retries'] = self.retries
        self.raw_data['modbus_failure_rate'] = failure_percentage
        self.raw_data['modbus_retry_rate'] = retry_percentage

    def publish_state(self):
        try:
            data = {}
            for register in self.config['registers']:
                if register['name'] in self.raw_data:
                    raw_value = self.raw_data[register['name']]
                    value = self.translate_from_raw_value(register, raw_value)
                    data[register['name']] = value

            json_data = json.dumps(data, indent=2)
            self.client.publish(self.topic + "state_all",
                                json_data, retain=True)

            with open("data.json", "w") as write_file:
                write_file.write(json_data)
            if self.legacy_publish:
                self.publish_legacy_state()
        except Exception:
            logging.info(traceback.format_exc())
        time.sleep(self.refresh_interval)

    def publish_legacy_state(self):
        for register in self.config['registers']:
            logging.debug('Publishing %s:%s', self.topic +
                          register.get("name"), self.raw_data.get(register.get("name")))
            try:
                value = self.translate_from_raw_value(
                    register, self.raw_data.get(register.get("name")))
                self.client.publish(
                    self.topic + register.get("name"), value, retain=False)
            except Exception:
                logging.debug(traceback.format_exc())

    def publish_mqtt_discovery_bridge(self):
        payload = {
            "device": {
                "identifiers": [f"sofar2mqtt_python_bridge_{self.raw_data.get('serial_number')}"],
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
            "unique_id": f"bridge_{self.raw_data.get('serial_number')}_connection_state_sofar2mqtt_python",
        }

        try:
            topic = f"homeassistant/binary_sensor/{self.raw_data.get('serial_number')}/connection_state/config"
            logging.info(f"Publishing bridge via MQTT to {topic}")
            self.client.publish(topic, json.dumps(payload), retain=False)
            logging.info(f"Publishing bridge online")
            self.client.publish("sofar2mqtt_python/bridge",
                                "online", retain=False)
        except Exception:
            logging.info(traceback.format_exc())

    def publish_mqtt_discovery(self):
        logging.info(f"Publishing controls via MQTT")
        while not self.raw_data.get("sw_version_com") and not self.raw_data.get("hw_version"):
            logging.info(
                f"SW Version and HW Version not available yet. Waiting for 5 seconds")
            time.sleep(5)

        for register in self.config['registers']:
            if 'ha' not in register:
                continue

            try:
                default_payload = {
                    "name": register['name'],
                    "state_topic": "sofar/state_all",
                    "unique_id": f"{self.raw_data.get('serial_number')}_{register['name']}",
                    "entity_id": f"sofar_{register['name']}",
                    "enabled_by_default": "true",
                    "device": {
                        "name": f"Sofar",
                        "sw_version": self.raw_data.get("sw_version_com"),
                        "hw_version": self.raw_data.get("hw_version"),
                        "manufacturer": "Sofar",
                        "model": self.raw_data.get('model'),
                        "configuration_url": "https://github.com/rjpearce/sofar2mqtt-python",
                        "identifiers": [f"{self.raw_data.get('serial_number')}"]
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

    def terminate(self, status_code=0):
        logging.info("Terminating")
        logging.info(f"Publishing offline to sofar2mqtt_python/bridge")
        self.client.publish("sofar2mqtt_python/bridge",
                            "offline", retain=False)
        self.client.loop_stop()
        exit(status_code)

    def main(self):
        """ Main method """
        signal.signal(signal.SIGTERM, self.signal_handler)
        signal.signal(signal.SIGINT, self.signal_handler)
        if not self.daemon:
            self.update_state()
            self.publish_state()
        while (self.daemon):
            self.requests = 0
            self.failures = 0
            self.failed = []
            self.retries = 0
            try:
                self.client.publish(
                    "sofar2mqtt_python/bridge", "online", retain=False)
            except Exception:
                logging.info(traceback.format_exc())
            self.update_state()
            self.publish_state()
            time.sleep(self.refresh_interval)
            self.iteration += 1
        self.terminate(status_code=0)


    def write_register_special(self, registeraddress, functioncode, value):
        with self.mutex:
            reg_int = int(registeraddress, 16)

            logging.info(
                f"Writing {registeraddress}({reg_int}) functioncode: {functioncode} with {value}"
            )

            # Payload = [cmd][param] (each uint16)
            payload = struct.pack(">HH", reg_int, value)

            logging.info("Payload (no CRC): %s", payload.hex(" "))

            response = self.instrument._perform_command(
                int(functioncode),   # 0x42
                payload
            )

            logging.info("Raw response: %s", response.hex(" "))
        return response

    def write_register(self, register, value):
        """ Write value to register """
        with self.mutex:
            retry = self.write_retry
            logging.info(
                f"Writing {register['register']}({int(register['register'], 16)}) with {value}({value})")
            signed = False
            success = False
            retries = 0
            failed = 0
            if 'signed' in register:
                signed = register['signed']
            while retry > 0 and not success:
                try:
                    if register['type'] == 'U16':
                        self.instrument.write_register(
                            int(register['register'], 16), int(value))
                    elif register['type'] == 'I32':
                        # split the value to a byte
                        values = struct.pack(">l", value)
                        # split low and high byte
                        low = struct.unpack(">H", bytearray(
                            [values[0], values[1]]))[0]
                        high = struct.unpack(
                            ">H", bytearray([values[2], values[3]]))[0]
                        # send the registers
                        self.instrument.write_registers(int(register['register'], 16), [
                                                        0, 0, low, high, low, high])
                except minimalmodbus.NoResponseError as e:
                    logging.debug(
                        f"Failed to write_register {register['name']} {str(e)}")
                    retry = retry - 1
                    retries = retries + 1
                    time.sleep(self.write_retry_delay)
                except minimalmodbus.InvalidResponseError as e:
                    logging.debug(
                        f"Failed to write_register {register['name']} {str(e)}")
                    retry = retry - 1
                    retries = retries + 1
                    time.sleep(self.write_retry_delay)
                except serial.serialutil.SerialException as e:
                    logging.debug(
                        f"Failed to write_register {register['name']} {str(e)}")
                    retry = retry - 1
                    retries = retries + 1
                    time.sleep(self.write_retry_delay)
                success = True
            if success:
                logging.info(
                    'Modbus Write Request: %s successful. Retries: %d', register['name'], retries)
            else:
                logging.error(
                    'Modbus Write Request: %s failed. Retry exhausted. Retries: %d', register['name'], retries)

    def write_registers_with_retry(self, start_register, values):
        """ Write values with a retry mechanism """
        retry = self.write_retry
        logging.info(f"Writing {start_register} with {values}")
        signed = False
        success = False
        retries = 0
        failed = 0
        while retry > 0 and not success:
            try:
                with self.mutex:
                    self.instrument.write_registers(
                        int(start_register, 16), values)
            except minimalmodbus.NoResponseError as e:
                logging.debug(
                    f"Failed to write_register {start_register} {str(e)}")
                retry = retry - 1
                retries = retries + 1
                time.sleep(self.write_retry_delay)
            except minimalmodbus.InvalidResponseError as e:
                logging.debug(
                    f"Failed to write_register {start_register} {str(e)}")
                retry = retry - 1
                retries = retries + 1
                time.sleep(self.write_retry_delay)
            except serial.serialutil.SerialException as e:
                logging.debug(
                    f"Failed to write_register {start_register} {str(e)}")
                retry = retry - 1
                retries = retries + 1
                time.sleep(self.write_retry_delay)
            success = True
        if success:
            logging.info(
                'Modbus Write Request: %s successful. Retries: %d', start_register, retries)
        else:
            logging.error(
                'Modbus Write Request: %s failed. Retry exhausted. Retries: %d', start_register, retries)

    def read_register(self, registeraddress, read_type, signed, registers=1):
        """ Read value from register with a retry mechanism """
        with self.mutex:
            value = None
            retry = self.retry
            while retry > 0 and value is None:
                try:
                    self.requests += 1
                    if read_type == "register":
                        value = self.instrument.read_register(
                            registeraddress, 0, functioncode=3, signed=signed)
                    elif read_type == "long":
                        value = self.instrument.read_long(
                            registeraddress, functioncode=3, signed=True, number_of_registers=2)
                    elif read_type == "string":
                        value = self.instrument.read_string(
                            registeraddress, functioncode=3, number_of_registers=registers)
                except minimalmodbus.NoResponseError as e:
                    logging.debug(
                        f"Failed to read_register {registeraddress} {str(e)}")
                    retry = retry - 1
                    self.retries = self.retries + 1
                    self.failure_pattern += "r"
                    time.sleep(self.retry_delay)
                except minimalmodbus.InvalidResponseError as e:
                    logging.debug(
                        f"Failed to read_register {registeraddress} {str(e)}")
                    retry = retry - 1
                    self.retries = self.retries + 1
                    self.failure_pattern += "i"
                    time.sleep(self.retry_delay)
                except serial.serialutil.SerialException as e:
                    logging.debug(
                        f"Failed to read_register {registeraddress} {str(e)}")
                    retry = retry - 1
                    self.retries = self.retries + 1
                    self.failure_pattern += "x"
                    time.sleep(self.retry_delay)

            if retry == 0:
                self.failures = self.failures + 1
                self.failure_pattern += "f"
                self.failed.append(registeraddress)
            if value is None:
                self.failure_pattern += "n"
            else:
                self.failure_pattern += "."
            return value

    def is_valid_serial_number(self, serial_number):
        """ Check if the serial number is valid """
        logging.info(
            f"Checking validity of Serial number: {str(serial_number)} length: {len(serial_number)}")
        if len(serial_number) == 14:
            return serial_number[0] == 'S' and serial_number[1].isalpha() and serial_number[2:].isalnum()
        elif len(serial_number) == 20:
            return serial_number[0] == 'S' and serial_number[1:].isalnum()
        return False

    def read_ascii(self, start, count):
        try:
            regs = self.instrument.read_registers(start, count, functioncode=3)
        except Exception as e:
            logging.debug(f"Error reading registers at {hex(start)}: {e}")
            return None

        chars = []
        for val in regs:
            hi = (val >> 8) & 0xFF
            lo = val & 0xFF

            # Sofar stores ASCII in HIGH BYTE first for this model
            for b in (hi, lo):
                if b == 0:
                    continue
                c = chr(b)
                if c.isprintable():
                    chars.append(c)

        return "".join(chars)

    def determine_serial_number(self):
        """Determine the serial number from the inverter."""
  
        # 1) First location: 0x2001–0x2007 (14 chars)
        serial = self.read_ascii(0x2001, 7)
        if serial and self.is_valid_serial_number(serial):
            logging.info(f"Valid Serial number found at first location: {serial}")
            return serial

        # 2) Second location: 0x0445–0x044B (14 chars)
        serial = self.read_ascii(0x0445, 7)
        if serial and self.is_valid_serial_number(serial):
            logging.info(f"Valid Serial number found at second location: {serial}")
            return serial

        # 3) Third location: 0x0445–0x044C (16 chars) + 0x0470–0x0471 (4 chars)
        part1 = self.read_ascii(0x0445, 8)   # 16 chars
        part2 = self.read_ascii(0x0470, 2)   # 4 chars
        serial = part1 + part2

        if part1 is not None and part2 is not None:
            # Sofar rule: if part2 is empty → 14-digit serial
            if part2.strip("") == "":
                if self.is_valid_serial_number(part1):
                    logging.info(f"Valid 14-digit Serial number found at third location: {part1}")
                    return part1
            else:
                serial = part1 + part2
                if self.is_valid_serial_number(serial):
                    logging.info(f"Valid 20-digit Serial number found at third location: {serial}")
                    return serial

        logging.error("Failed to determine serial number")
        return None


    def determine_model(self):
        """ Determine the model of the inverter based on the serial number """
        serial_number = self.raw_data.get('serial_number') 
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

        modbus_protocol = protocol_mapping.get(self.raw_data.get('model'), False)
        if modbus_protocol:
            logging.info(f"Modbus protocol determined: {modbus_protocol}")
        else:
            logging.error("Failed to determine Modbus protocol from model")
        return modbus_protocol

    def convert_value(self, register, value):
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
        if register and 'modes' in register:
            return next((k for k, v in register['modes'].items() if v == value), value)
        return value

    def write_register_block(self, block_name, update_register, new_value):
        """ Write a specific register block from configuration to Modbus """
        block = next((b for b in self.config.get(
            'write_register_blocks', []) if b['name'] == block_name), None)
        if not block:
            logging.error(f"Block {block_name} not found in configuration")
            return

        required_length = int(block['length'])
        values = []
        for register_name in block['registers']:
            if register_name == update_register:
                register = self.get_register(register_name)
                if register:
                    new_raw_value = self.translate_to_raw_value(
                        register, new_value)
                    if not validate_new_value(register, new_raw_value):
                        return
                    raw_value = new_raw_value
                else:
                    logging.error(
                        f"Register {register_name} not found in configuration")
                    continue
            else:
                raw_value = self.raw_data.get(register_name)
            if raw_value is None:
                logging.error(
                    f"Value for {register_name} not found in raw data. Skipping block {block['name']}")
                return
            values.append(raw_value)
        if 'append' in block:
            for append_item in block['append']:
                values.append(append_item)

        register = self.get_register(update_register)
        new_raw_value = self.translate_to_raw_value(register, new_value)

        retry = self.write_retry + 10
        while retry > 0:
            current_raw_value = self.raw_data[update_register]
            current_value = self.translate_from_raw_value(
                register, current_raw_value)
            if current_raw_value == new_raw_value:
                logging.info(
                    f"Current value for {register['name']}: {current_raw_value} ({current_value}). Matches desired value: {new_raw_value} ({new_value}).")
                retry = 0
            else:
                if len(values) < required_length:
                    logging.error(
                        f"Length of values in block is less than required length for block {block['name']}. Skipping write operation. Values: {values}")
                    return
                logging.info(
                    f"Current value for {register['name']}: {current_raw_value} ({current_value}), attempting to set it to: {new_raw_value} ({new_value}). Retries remaining: {retry}")
                logging.info(
                    f"Would write {block['start_register']} with {values[:required_length]}")
                self.write_registers_with_retry(
                    block['start_register'], values[:required_length])
                # logging.info(f"Reference values: {[0, 0, 1, 560, 540, 425, 470, 10000, 10000, 90, 90, 250, 480, 1, 10, 1]}")
                #                                  [0, 0, 1, 540, 530, 425, 470, 10000, 10000, 89, 90, 250, 480, 1, 10, 1]
                # self.write_registers_with_retry(block['start_register'], [0, 0, 1, 560, 540, 425, 470, 10000, 10000, 90, 90, 250, 480, 1, 10, 1])
                time.sleep(self.write_retry_delay + 5)
                retry = retry - 1

    def get_register(self, register_name):
        """ Look up a register from self.config['registers'] """
        register = next(
            (r for r in self.config['registers'] if r['name'] == register_name), None)
        if register is None:
            logging.error(
                f"Register {register_name} not found in configuration")
        return register
    
    def read_event_timestamp(self,
                            reg_yM,
                            reg_dH,
                            reg_mS):
        """
        Reads inverter history timestamp registers and returns a datetime object.

        Register format:
        reg_yM (0x1481):
            High byte = year (last two digits)
            Low byte  = month

        reg_dH (0x1482):
            High byte = day
            Low byte  = hour

        reg_mS (0x1483):
            High byte = minute
            Low byte  = second
        """
        logging.info(f"Reading event timestamp from registers: yM={reg_yM}, dH={reg_dH}, mS={reg_mS}")
        if reg_yM == "" or reg_dH == "" or reg_mS == "": return None

        # Read raw register values
        yM = self.instrument.read_register(int(reg_yM, 16), 0, 3)
        dH = self.instrument.read_register(int(reg_dH, 16), 0, 3)
        mS = self.instrument.read_register(int(reg_mS, 16), 0, 3)

        logging.info(f"Read event timestamp registers: yM={yM}, dH={dH}, mS={mS}")

        # Extract bytes
        year_2digit = (yM >> 8) & 0xFF
        month       = yM & 0xFF

        day         = (dH >> 8) & 0xFF
        hour        = dH & 0xFF

        minute      = (mS >> 8) & 0xFF
        second      = mS & 0xFF

        # Convert 2‑digit year to full year (assume 2000–2099)
        year_full = 2000 + year_2digit

        # Build datetime
        timestamp = datetime.datetime(year_full, month, day, hour, minute, second)

        return timestamp

    def format_history_event(self, raw_value):
        entry = self.config.get('error_codes', {}).get(str(raw_value), {})
        name = entry.get("name", "")
        description = entry.get("description", "")

        if name and description:
            return f"{name} – {description}"
        return name or str(raw_value)


    def translate_from_raw_value(self, register, raw_value):
        """ Translate raw value to a normalized value using the function and factor """
        if 'function' in register:
            if register['function'] == 'multiply':
                return raw_value * register['factor']
            elif register['function'] == 'divide':
                return raw_value / register['factor']
            elif register['function'] == 'mode':
                return register['modes'].get(str(raw_value), raw_value)
            elif register['function'] == 'history_event_map':
                return self.format_history_event(raw_value)
            elif register['function'] == 'bit_field':
                length = len(register['fields'])
                fields = []
                for n in reversed(range(length)):
                    if raw_value & (1 << ((length-1)-n)):
                        fields.append(register['fields'][n])
                return ','.join(fields)
            elif register['function'] == 'high_bit_low_bit':
                high = raw_value >> 8  # shift right
                low = raw_value & 255  # apply bitmask
                # combine and pad 2 zeros
                return f"{high:02}{register['join']}{low:02}"
        return raw_value

    def translate_to_raw_value(self, register, value):
        """ Undo the operation performed by translate_from_raw_value """
        if 'function' in register:
            if register['function'] == 'int':
                return int(value)
            if register['function'] == 'multiply':
                return int(float(value) / register['factor'])
            elif register['function'] == 'divide':
                return int(float(value) * register['factor'])
            elif register['function'] == 'mode':
                return int(next((k for k, v in register['modes'].items() if v == value), value))
            elif register['function'] == 'bit_field':
                fields = value.split(',')
                raw_value = 0
                for field in fields:
                    if field in register['fields']:
                        raw_value |= (
                            1 << (len(register['fields']) - 1 - register['fields'].index(field)))
                return raw_value
            elif register['function'] == 'high_bit_low_bit':
                high, low = map(int, value.split(register['join']))
                return (high << 8) | low
        return int(value)


def validate_new_value(register, new_value):
    """ Validate the new value based on the register's min, max, and modes """
    if 'min' in register and new_value < register['min']:
        logging.error(
            f"Value {new_value} is less than the minimum allowed value {register['min']} for register {register['name']}")
        return False
    if 'max' in register and new_value > register['max']:
        logging.error(
            f"Value {new_value} is greater than the maximum allowed value {register['max']} for register {register['name']}")
        return False
    if 'function' in register and register['function'] == 'mode' and str(new_value) not in register['modes']:
        logging.error(
            f"Value {new_value} is not a valid mode for register {register['name']}")
        return False
    return True


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
    sofar = Sofar(daemon, retry, retry_delay, write_retry, write_retry_delay, refresh_interval, broker,
                  port, username, password, ca_certs, topic, write_topic, log_level, device, legacy_publish)
    sofar.main()


# pylint: disable=no-value-for-parameter
if __name__ == '__main__':
    main()
