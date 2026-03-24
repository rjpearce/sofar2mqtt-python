"""Data models for Sofar2MQTT."""

from sofar2mqtt.models.inverter_config import InverterConfig
from sofar2mqtt.models.register import HomeAssistantConfig, RegisterDefinition, WriteRegisterBlock

__all__ = [
    "RegisterDefinition",
    "HomeAssistantConfig",
    "WriteRegisterBlock",
    "InverterConfig",
]
