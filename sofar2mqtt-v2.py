#!/usr/bin/python3
""" Sofar 2 MQQT 
  V1.0 Created by Matt Nichols 2021
  V2.0 Updated by Richard Pearce 
    * Added a a retry mechanism
    * Added daemon mode
    * Split the data from the Python code (requires: sofar-hyd-ep.json and sofar-me-3000.json)
    * Added support the HYD-EP models. 
"""
import json
import time
import logging
import click
import minimalmodbus
import serial
from paho.mqtt import publish
import requests

logging.basicConfig(format='%(asctime)s %(message)s', level=logging.DEBUG)
logging.info('Getting Consumption data')

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
    def __init__(self, config_file_path, daemon, retry, retry_delay, refresh_interval, broker, topic, log_level):
        self.config = load_config(config_file_path)
        self.daemon = daemon
        self.retry = retry
        self.retry_delay = retry_delay
        self.refresh_interval = refresh_interval
        self.broker = broker
        self.topic = topic
        self.log_level = log_level
        self.requests = 0
        self.failures = 0
        self.instrument = minimalmodbus.Instrument('/dev/ttyUSB0', 1)
        self.instrument.serial.baudrate = 9600   # Baud
        self.instrument.serial.bytesize = 8
        self.instrument.serial.parity = serial.PARITY_NONE
        self.instrument.serial.stopbits = 1
        # self.instrument.serial.timeout  = 5   # seconds

    def main(self):
        """ Main method """
        while self.daemon:
            for register in self.config['registers']:
                value = self.read_value(int(register['register'], 16))
                if value is None:
                    continue
                if 'combine' in register:
                    value = value + \
                        self.read_value(int(register['combine'],16))
                if 'function' in register:
                    if register['function'] == 'multiply':
                        value = value * register['factor']
                    elif register['function'] == 'divide':
                        value = value / register['factor']
                    elif register['function'] == 'mode':
                        value = register['modes'][str(value)]
                logging.debug('%s:%s', register['name'], value)
                publish.single(self.topic + register['name'], value, hostname=self.broker)

            logging.info('Failures: %d/%d %s', self.failures, self.requests, str((self.failures/self.requests)*100) + '%')
            publish.single(self.topic + 'modbus_failures', self.failures, hostname=self.broker)
            publish.single(self.topic + 'modbus_requests', self.requests, hostname=self.broker)
            publish.single(self.topic + 'modbus_failure_rate',
                        (self.failures/self.requests)*100, hostname=self.broker)
            time.sleep(self.refresh_interval)

    def read_value(self, register):
        """ Read value from register with a retry mechanism """
        value = None
        retry = self.retry
        while retry > 0 and value is None:
            try:
                self.requests +=1
                value = self.instrument.read_register(
                    register, 0, functioncode=3, signed=False)
            except minimalmodbus.NoResponseError:
                retry = retry - 1
                self.failures = self.failures + 1
                time.sleep(self.retry_delay)
            except minimalmodbus.InvalidResponseError:
                retry = retry - 1
                self.failures = self.failures + 1
                time.sleep(self.retry_delay)
        return value


@click.command()
@click.option(
    '--config-file',
    default='sofar-hyd-ep.json',
    required=True,
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
    default=10,
    type=int,
    help='Number of retries per register before giving up',
)
@click.option(
    '--retry-delay',
    default=0.1,
    type=float,
    help='Delay before retrying',
)
@click.option(
    '--refresh-interval',
    default=10,
    type=int,
    help='Refresh every n seconds',
)
@click.option(
    '--broker',
    required=True,
    help='MQTT broker address',
)
@click.option(
    '--topic',
    default='sofar/',
    required=True,
    help='MQTT topic',
)
@click.option(
    '--log-level',
    default='INFO',
    required=False,
)
# pylint: disable=too-many-arguments
def main(config_file, daemon, retry, retry_delay, refresh_interval, broker, topic, log_level):
    """Main"""
    sofar = Sofar(config_file, daemon, retry, retry_delay, refresh_interval, broker, topic, log_level)
    sofar.main()

# pylint: disable=no-value-for-parameter
if __name__ == '__main__':
    main()
