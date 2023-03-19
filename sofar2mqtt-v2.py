#!/usr/bin/python3
""" Sofar 2 MQQT 
  V1.0 Created by Matt Nichols 2021
  V2.0 Updated by Richard Pearce 
    * Added a a retry mechanism
    * Added daemon mode
    * Split the data from the Python code (requires: sofar-hyd-ep.json and sofar-me-3000.json)
    * Added support the HYD-EP models. 
"""
import datetime
import json
import time
import logging
import click
import traceback
import minimalmodbus
import serial
from paho.mqtt import publish
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
    def __init__(self, config_file_path, daemon, retry, retry_delay, refresh_interval, broker, port, username, password, topic, log_level, device):
        self.config = load_config(config_file_path)
        self.daemon = daemon
        self.retry = retry
        self.retry_delay = retry_delay
        self.refresh_interval = refresh_interval
        self.broker = broker
        self.port = port
        self.username = username
        self.password = password
        self.topic = topic
        self.requests = 0
        self.failures = 0
        self.failed = []
        self.retries = 0
        self.instrument = None
        self.device = device
        self.data = {}
        self.log_level = logging.getLevelName(log_level)
        logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=self.log_level)


    def setup_instrument(self):
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
        self.setup_instrument()
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

        failure_percentage = str(round(self.failures / (self.requests+self.retries)*100,2))+'%'
        retry_percentage = str(round(self.retries / (self.requests)*100,2))+'%'
        logging.info('Modbus Requests: %d Retries: %d (%s) Failures: %d (%s)', self.requests, self.retries, retry_percentage, self.failures, failure_percentage)
        self.publish('modbus_failures', self.failures)
        self.publish('modbus_requests', self.requests)
        self.publish('modbus_retries', self.retries)
        self.publish('modbus_failure_rate', failure_percentage)
        self.publish('modbus_retry_rate', retry_percentage)
        self.instrument.serial.close()

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
        self.data[key] = value
        auth = None
        logging.debug('Publishing %s:%s', self.topic + key, value)
        if self.username is not None and self.password is not None:
            auth = {"username": self.username, "password": self.password}
        try:
            publish.single(self.topic + key, value, hostname=self.broker, port=self.port, auth=auth, retain=True)
        except Exception:
            logging.debug(traceback.format_exc())

    def read_value(self, registeraddress, read_type, signed):
        """ Read value from register with a retry mechanism """
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
                        registeraddress, functioncode=3, signed=signed)
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
    default='sofar-hyd-ep.json',
    help='Configuration file to use',
)
@click.option(
    '--daemon',
    is_flag=True,
    default=False,
    help='Run as a daemon',
)
@click.option(
    '--retry',
    default=2,
    type=int,
    help='Number of read retries per register before giving up',
)
@click.option(
    '--retry-delay',
    default=0.1,
    type=float,
    help='Delay before retrying read',
)
@click.option(
    '--refresh-interval',
    default=5,
    type=int,
    help='Refresh data every n seconds',
)
@click.option(
    '--broker',
    default='localhost',
    help='MQTT broker address',
)
@click.option(
    '--port',
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
    default='sofar/',
    help='MQTT topic',
)
@click.option(
    '--log-level',
    default='INFO',
    type=click.Choice(['INFO', 'DEBUG'], case_sensitive=False),
    help='Log Level'
)
@click.option(
    '--device',
    default='/dev/ttyUSB0',
    help='RS485/USB Device'
)
# pylint: disable=too-many-arguments
def main(config_file, daemon, retry, retry_delay, refresh_interval, broker, port, username, password, topic, log_level, device):
    """Main"""
    sofar = Sofar(config_file, daemon, retry, retry_delay, refresh_interval, broker, port, username, password, topic, log_level, device)
    sofar.main()

# pylint: disable=no-value-for-parameter
if __name__ == '__main__':
    main()
