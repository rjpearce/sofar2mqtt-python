"""Sofar2MQTT - Sofar inverter to MQTT integration with Home Assistant auto-discovery."""

__version__ = "4.0.1"
__author__ = "Youri"
__email__ = "youri@example.com"

from sofar2mqtt.models import (
    RegisterDefinition,
    HomeAssistantConfig,
    WriteRegisterBlock,
    InverterConfig,
)
from sofar2mqtt.core.modbus_client import ModbusClient
from sofar2mqtt.core.sofar_client import SofarClient
from sofar2mqtt.mqtt.client import MqttClient
from sofar2mqtt.mqtt.discovery import HomeAssistantDiscovery, build_device_info
from sofar2mqtt.transformations.converter import ValueConverter, combine_registers, read_ascii
from sofar2mqtt.config.loader import ConfigLoader, load_config
from sofar2mqtt.utils.retry import retry_on_failure

__all__ = [
    # Models
    "RegisterDefinition",
    "HomeAssistantConfig",
    "WriteRegisterBlock",
    "InverterConfig",
    # Core
    "ModbusClient",
    "SofarClient",
    # MQTT
    "MqttClient",
    "HomeAssistantDiscovery",
    "build_device_info",
    # Transformations
    "ValueConverter",
    "combine_registers",
    "read_ascii",
    # Config
    "ConfigLoader",
    "load_config",
    # Utils
    "retry_on_failure",
]


# Deprecated: keep for backward compatibility
def __getattr__(name):
    if name == "register":
        from sofar2mqtt.models import register  # noqa

        return register
    elif name == "inverter_config":
        from sofar2mqtt.models import inverter_config  # noqa

        return inverter_config
    elif name == "modbus_client":
        from sofar2mqtt.core import modbus_client  # noqa

        return modbus_client
    elif name == "sofar_client":
        from sofar2mqtt.core import sofar_client  # noqa

        return sofar_client
    elif name == "client":
        from sofar2mqtt.mqtt import client  # noqa

        return client
    elif name == "discovery":
        from sofar2mqtt.mqtt import discovery  # noqa

        return discovery
    elif name == "converter":
        from sofar2mqtt.transformations import converter  # noqa

        return converter
    elif name == "loader":
        from sofar2mqtt.config import loader  # noqa

        return loader
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
