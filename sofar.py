#!/usr/bin/python3

import click
import minimalmodbus
import json
import serial
import paho.mqtt.publish as publish
import time
import requests
import logging

instrument = minimalmodbus.Instrument('/dev/ttyUSB0', 1, debug=False) # port name, slave address 
instrument.serial.baudrate = 9600   # Baud
instrument.serial.bytesize = 8
instrument.serial.parity   = serial.PARITY_NONE
instrument.serial.stopbits = 1
#instrument.serial.timeout  = 5   # seconds

requests = 0
failures = 0

def load_config(config_file_path):
    config = {}
    with open (config_file_path, mode='r') as config_file:
      config = json.loads(config_file.read())
    return config

def read_value(register, retry, retry_delay):
    global failures, requests
    value = None
    while retry >0 and value == None:
        try:   
            requests = requests + 1
            value = instrument.read_register(register, 0, functioncode=3, signed=False) 
        except minimalmodbus.NoResponseError as e:
            #print(e)
            retry = retry - 1
            failures = failures + 1
            time.sleep(retry_delay)
        except minimalmodbus.InvalidResponseError as e:
            #print(e)
            retry = retry - 1
            failures = failures + 1
            time.sleep(retry_delay)
    return value


@click.command()
@click.option(
    '--config-file',
    default='sofar-hyd-ep.json',
    required=True,
    help='Configuration file to use',
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

def main(config_file, retry, retry_delay, refresh_interval, broker, topic, log_level):
    """Main"""
    config = load_config(config_file)
    logging.basicConfig(format='%(asctime)s %(message)s', level=logging.DEBUG)
    logging.info('Getting Consumption data')

    while(True):
        for register in config['registers']:
            value = read_value(int(register['register'], 16), retry, retry_delay)
            if value == None:
                continue
            if 'combine' in register:
                value = value + read_value(int(register['combine'], 16), retry, retry_delay)
            if 'function' in register:
                if register['function'] == 'multiply':
                    value = value * register['factor']
                elif register['function'] == 'divide':
                    value = value / register['factor']
                elif register['function'] == 'mode':
                    value = register['modes'][str(value)]
            logging.debug(f"{register['name']}:{value}")
            publish.single(topic + register['name'],value, hostname=broker)

        logging.info(f"Failures: {failures}/{requests} {failures/requests*100}")
        publish.single(topic + 'modbus_failures', failures, hostname=broker)
        publish.single(topic + 'modbus_requests', requests, hostname=broker)
        publish.single(topic + 'modbus_failure_rate', (failures/requests)*100, hostname=broker)
        time.sleep(refresh_interval)

if __name__ == '__main__':
    main()
