"""Home Assistant MQTT discovery for Sofar2MQTT."""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class HomeAssistantDiscovery:
    """Manages Home Assistant MQTT auto-discovery for Sofar inverters."""

    def __init__(self, mqtt_client, serial_number: str):
        """Initialize discovery manager."""
        self.mqtt = mqtt_client
        self.serial = serial_number

    def publish_bridge_status(self) -> None:
        """Publish bridge connectivity status sensor."""
        payload = {
            "device": {
                "identifiers": [f"sofar2mqtt_python_bridge_{self.serial}"],
                "manufacturer": "Sofar2Mqtt-Python",
                "model": "Bridge",
                "name": "Sofar2Mqtt Python Bridge",
                "sw_version": "4.0.1",
            },
            "device_class": "connectivity",
            "entity_category": "diagnostic",
            "name": "Connection state",
            "object_id": f"sofar2mqtt_python_bridge_connection_state_{self.serial}",
            "payload_off": "offline",
            "payload_on": "online",
            "state_topic": "sofar2mqtt_python/bridge",
            "unique_id": f"bridge_{self.serial}_connection_state_sofar2mqtt_python",
        }

        topic = f"homeassistant/binary_sensor/{self.serial}/connection_state/config"
        self.mqtt.publish(topic, json.dumps(payload), retain=True)

        # Publish online status
        self.mqtt.publish("sofar2mqtt_python/bridge", "online", retain=True)

        logger.info(f"Published bridge discovery for {self.serial}")

    def discover_all(self, registers: list, device_id: str, device_name: str) -> None:
        """Publish discovery configuration for all registers."""
        # Publish bridge status first
        self.publish_bridge_status()

        device_info = build_device_info(
            {"model": device_name}, {"sw_version_com": "unknown", "hw_version": "unknown"}
        )
        for register in registers:
            self.publish_register_discovery(
                register.model_dump() if hasattr(register, "model_dump") else register, device_info
            )

    def publish_register_discovery(
        self, register: dict[str, Any], device_info: dict[str, Any]
    ) -> None:
        """Publish discovery configuration for a single register."""
        if "ha" not in register:
            return

        try:
            # Build base discovery payload
            payload = {
                "name": register["ha"].get("name", register["name"]),
                "state_topic": "sofar/state_all",
                "unique_id": f"{self.serial}_{register['name']}",
                "device": device_info,
                "availability": [{"topic": "sofar2mqtt_python/bridge", "value_template": "online"}],
            }

            # Merge HA-specific configuration (skip None values to preserve defaults)
            ha_config = register["ha"]
            for key, value in ha_config.items():
                if key != "control" and value is not None:
                    payload[key] = value

            # Determine entity type and topic
            control_type = ha_config.get("control") or "sensor"
            topic = f"homeassistant/{control_type}/sofar_{register['name']}/config"

            self.mqtt.publish(topic, json.dumps(payload), retain=True)

        except Exception as e:
            logger.error(f"Failed to publish discovery for {register['name']}: {e}")


def build_device_info(config: dict[str, Any], raw_data: dict[str, Any]) -> dict[str, Any]:
    """Build device information for Home Assistant."""
    return {
        "name": config.get("model", "Sofar Inverter"),
        "sw_version": raw_data.get("sw_version_com", "unknown"),
        "hw_version": raw_data.get("hw_version", "unknown"),
        "manufacturer": "Sofar",
        "model": config.get("model", "Unknown"),
        "configuration_url": "https://github.com/rjpearce/sofar2mqtt-python",
        "identifiers": [raw_data.get("serial_number", "unknown")],
    }
