#!/usr/bin/python3
""" Sofar 2 MQQT """
import datetime
import json
import time
import logging
import click
import traceback
import minimalmodbus
import serial
import struct
import threading
import paho.mqtt.client as mqtt
import requests

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
    def __init__(self, config_file_path, daemon, retry, retry_delay, write_retry, write_retry_delay, refresh_interval, broker, port, username, password, topic, write_topic, log_level, device):
        self.config = load_config(config_file_path)
        self.write_registers = []
        for register in self.config['registers']:
            if "write" in register:
                if register["write"]:
                    self.write_registers.append(register)
        self.daemon = daemon
        self.retry = retry
        self.retry_delay = retry_delay
        self.write_retry = retry
        self.write_retry_delay = write_retry_delay
        self.refresh_interval = refresh_interval
        self.broker = broker
        self.port = port
        self.username = username
        self.password = password
        self.topic = topic
        self.write_topic = write_topic
        self.requests = 0
        self.failures = 0
        self.failed = []
        self.retries = 0
        self.instrument = None
        self.device = device
        self.data = {}
        self.log_level = logging.getLevelName(log_level)
        logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=self.log_level)
        self.mutex = threading.Lock()
        self.client = mqtt.Client(client_id="sofar2mqtt", userdata=None, protocol=mqtt.MQTTv5, transport="tcp")
        self.client.enable_logger(logger=logging)
        self.setup_mqtt()
        self.setup_instrument()
        
    def on_connect(self, client, userdata, flags, rc, properties=None):
        logging.info("MQTT "+mqtt.connack_string(rc))
        if rc == 0:
            try:
                for register in self.write_registers:
                    logging.info(f"Subscribing to {self.write_topic}/{register['name']}")
                    client.subscribe(f"{self.write_topic}/{register['name']}", qos=0, options=None, properties=None)
            except Exception:
                logging.info(traceback.format_exc())

    def on_disconnect(client, userdata, rc, properties=None):
        if rc != 0:
            logging.info("MQTT un-expected disconnect")

    def on_message(self, client, userdata, message, properties=None):
        found = False
        valid = False
        register_name = message.topic.split('/')[-1]
        payload = message.payload.decode("utf-8") 
        for register in self.write_registers:
            if register['name'] == register_name:
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
                                    self.write_value(register, int(new_mode))
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
                                        self.write_value(register, value)
                                        time.sleep(self.write_retry_delay)
                                        retry = retry - 1
                            else: 
                                logging.error(f"No current read value for {register['name']} skipping write operation. Please try again.")

        if not found:
            logging.error(f"Received a request to set an unknown register: {register_name} to {payload}")


    def setup_mqtt(self):
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        if self.username is not None and self.password is not None:
            self.client.username_pw_set(self.username, self.password)
            logging.info(f"MQTT connecting to broker {self.broker} port {self.port} with auth user {self.username}")
        else:
            logging.info(f"MQTT connecting to broker {self.broker} port {self.port} without auth")
        self.client.reconnect_delay_set(min_delay=1, max_delay=300)
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
            self.instrument.serial.timeout  = 0.1   # seconds
            self.instrument.clear_buffers_before_each_transaction = True
            self.instrument.close_port_after_each_call = True

    def read_and_publish(self):
        for register in self.config['registers']:
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
                if 'invert' in register:
                    if register['invert']:
                        if value > 0:
                            value = -abs(value)
                        else:
                            value = abs(value)
            else:
                read_type = 'register'
                if 'read_type' in register:
                    read_type = register['read_type']
                value = self.read_value(
                        int(register['register'], 16),
                        read_type,
                        signed
                )
            if value is None:
                continue

            else:
                # Inverter will return maximum 16-bit integer value when data not available (eg. grid usage when grid down)
                if value == 65535:
                    value = 0
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

            self.publish(register['name'], value)

        failure_percentage = round(self.failures / (self.requests+self.retries)*100,2)
        retry_percentage = round(self.retries / (self.requests)*100,2)
        logging.info(f"Modbus Requests: {self.requests} Retries: {self.retries} ({retry_percentage}%) Failures: {self.failures} ({failure_percentage}%)")
        self.publish('modbus_failures', self.failures)
        self.publish('modbus_requests', self.requests)
        self.publish('modbus_retries', self.retries)
        self.publish('modbus_failure_rate', failure_percentage)
        self.publish('modbus_retry_rate', retry_percentage)

    def main(self):
        """ Main method """
        if not self.daemon:
            self.read_and_publish()
        else:
            while self.daemon:
                now = datetime.datetime.now()
                """ Sleep for 35 seconds to allow the inverter to reset the stats at 00:00 """
                if (now.hour == 23 and now.minute == 59 and now.second >= 30):
                    logging.info('Snoozing 35 seconds')
                    time.sleep(35)
                self.read_and_publish()
                self.requests = 0
                self.failures = 0
                self.failed = []
                self.retries = 0
                time.sleep(self.refresh_interval)

    def publish(self, key, value):
        if key == 'energy_storage_mode':
            if key in self.data:
                if value != self.data[key]:
                    logging.info(f"energy_storage_mode has changed to: {value}")
        self.data[key] = value
        logging.debug('Publishing %s:%s', self.topic + key, value)
        try:
            self.client.publish(self.topic + key, value, retain=True)
        except Exception:
            logging.debug(traceback.format_exc())

    def write_value(self, register, value):
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

    def read_value(self, registeraddress, read_type, signed):
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

@click.command("cli", context_settings={'show_default': True})
@click.option(
    '--config-file',
    envvar='CONFIG_FILE',
    default='sofar-hyd-ep.json',
    help='Configuration file to use',
)
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
    type=float,
    help='Delay before retrying write',
)
@click.option(
    '--refresh-interval',
    envvar='REFRESH_INTERVAL',
    default=1,
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
# pylint: disable=too-many-arguments
def main(config_file, daemon, retry, retry_delay, write_retry, write_retry_delay, refresh_interval, broker, port, username, password, topic, write_topic, log_level, device):
    """Main"""
    sofar = Sofar(config_file, daemon, retry, retry_delay, write_retry, write_retry_delay, refresh_interval, broker, port, username, password, topic, write_topic, log_level, device)
    sofar.main()

# pylint: disable=no-value-for-parameter
if __name__ == '__main__':
    main()
