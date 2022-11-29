import json
import yaml
import click

def load_config(config_file_path):
    """ Load configuration file """
    config = {}
    with open(config_file_path, mode='r', encoding='utf-8') as config_file:
        config = json.loads(config_file.read())
    return config


@click.command("cli", context_settings={'show_default': True})
@click.option(
    '--config-file',
    default='sofar-hyd-ep.json',
    help='Configuration file to use',
)

# pylint: disable=too-many-arguments
def main(config_file):
    """Main"""
    config = load_config(config_file)
    yaml_filename = f"ha/{config_file.split('.')[0]}.yaml"
    mqtt_cfg = {
        "sensor": [
            { 
                "name": "Sofar:Modbus failures",
                "state_class": "measurement",
                "state_topic": "sofar/modbus_failures",
                "unique_id": "sofar_modbus_failures"
            },
            { 
                "name": "Sofar:Modbus requests",
                "state_class": "measurement",
                "state_topic": "sofar/modbus_requests",
                "unique_id": "sofar_modbus_requests"
            },
            { 
                "name": "Sofar:Modbus failure rate",
                "state_class": "measurement",
                "state_topic": "sofar/modbus_failure_rate",
                "unique_id": "sofar_modbus_failure_rate",
                "unit_of_measurement": "%"
            }
        ]
    }
    for register in config['registers']:
        if 'ha' in register:
            register['ha']['state_topic'] = f"sofar/{register['name']}"
            mqtt_cfg["sensor"].append(register['ha'])

    with open(yaml_filename, 'w') as outfile:
        yaml.dump(mqtt_cfg, outfile)

# pylint: disable=no-value-for-parameter
if __name__ == '__main__':
    main()