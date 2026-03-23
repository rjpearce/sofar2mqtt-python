"""MQTT client wrapper for Sofar2MQTT."""

import logging
import socket
from typing import Optional, Callable, Any
import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)


class MqttClient:
    """Wrapper around paho-mqtt client with Sofar-specific functionality."""

    def __init__(
        self,
        broker: str,
        port: int = 1883,
        username: Optional[str] = None,
        password: Optional[str] = None,
        ca_certs: Optional[str] = None,
        client_id: Optional[str] = None,
    ):
        """Initialize MQTT client."""
        self.broker = broker
        self.port = port
        self.username = username
        self.password = password
        self.ca_certs = ca_certs

        if client_id is None:
            client_id = f"sofar2mqtt-{socket.gethostname()}"

        self.client = mqtt.Client(
            client_id=client_id, userdata=None, protocol=mqtt.MQTTv5, transport="tcp"
        )

        self._connected = False

    def setup(self) -> None:
        """Configure MQTT client with authentication and TLS if needed."""
        # Set credentials if provided
        if self.username is not None and self.password is not None:
            self.client.username_pw_set(self.username, self.password)
            logger.info(f"MQTT connecting to {self.broker}:{self.port} with auth")
        else:
            logger.info(f"MQTT connecting to {self.broker}:{self.port} without auth")

        # Configure TLS if CA certs provided
        if self.ca_certs is not None:
            if self.port != 8883:
                logger.warning("CA certs provided but port is not 8883")
            self.client.tls_set(ca_certs=self.ca_certs)

        # Set reconnect delay
        self.client.reconnect_delay_set(min_delay=1, max_delay=300)

    def connect(self, clean_start: bool = True) -> None:
        """Establish connection to MQTT broker."""
        clean_start_flag = mqtt.MQTT_CLEAN_START_FIRST_ONLY if clean_start else 0

        self.client.connect(
            self.broker,
            port=self.port,
            keepalive=60,
            bind_address="",
            bind_port=0,
            clean_start=clean_start_flag,
            properties=None,
        )

        self.client.loop_start()
        logger.info("MQTT client loop started")

    def set_on_connect(self, callback: Callable) -> None:
        """Set the on_connect callback."""
        self.client.on_connect = callback

    def set_on_message(self, callback: Callable) -> None:
        """Set the on_message callback."""
        self.client.on_message = callback

    def set_on_disconnect(self, callback: Callable) -> None:
        """Set the on_disconnect callback."""
        self.client.on_disconnect = callback

    def subscribe(self, topic: str, qos: int = 0) -> None:
        """Subscribe to a MQTT topic."""
        self.client.subscribe(topic, qos=qos, options=None, properties=None)
        logger.debug(f"Subscribed to topic: {topic}")

    def publish(self, topic: str, payload: Any, qos: int = 0, retain: bool = False) -> None:
        """Publish a message to a MQTT topic."""
        try:
            self.client.publish(topic, payload=payload, qos=qos, retain=retain)
        except Exception as e:
            logger.error(f"Failed to publish to {topic}: {e}")

    def disconnect(self) -> None:
        """Disconnect from MQTT broker."""
        self.client.loop_stop()
        logger.info("MQTT client disconnected")

    def enable_logger(self, logger_obj: Any) -> None:
        """Enable paho-mqtt's internal logging."""
        self.client.enable_logger(logger=logger_obj)
