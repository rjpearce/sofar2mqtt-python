"""Main Sofar client orchestrating all components."""

import json
import logging
import signal
import socket
import time
from threading import Lock, Thread
from typing import Any

import paho.mqtt.client as paho

from sofar2mqtt.config.loader import load_config
from sofar2mqtt.core.modbus_client import ModbusClient
from sofar2mqtt.models.inverter_config import InverterConfig
from sofar2mqtt.mqtt.discovery import HomeAssistantDiscovery
from sofar2mqtt.transformations.converter import ValueConverter, combine_registers

logger = logging.getLogger(__name__)


class SofarClient:
    """Main client that orchestrates Modbus reading, MQTT publishing, and state management."""

    def __init__(
        self,
        config_path: str,
        modbus_device: str,
        mqtt_broker: str,
        mqtt_port: int = 1883,
        mqtt_user: str | None = None,
        mqtt_password: str | None = None,
        device_id: str = "sofar",
        device_name: str = "Sofar Inverter",
        poll_interval: int = 10,
        ha_discovery: bool = True,
    ):
        """Initialize Sofar client with all dependencies."""

        # Configuration
        self.config_path = config_path
        self.modbus_device = modbus_device
        self.mqtt_broker = mqtt_broker
        self.mqtt_port = mqtt_port
        self.mqtt_user = mqtt_user
        self.mqtt_password = mqtt_password
        self.device_id = device_id
        self.device_name = device_name
        self.poll_interval = poll_interval
        self.ha_discovery = ha_discovery

        # State
        self.running = False
        self.iteration = 0
        self.raw_data: dict[str, Any] = {}
        self._mutex = Lock()
        self._thread: Thread | None = None

        # Statistics
        self.requests = 0
        self.failures = 0
        self.retries = 0

        # Components (initialized in setup)
        self.modbus: ModbusClient | None = None
        self.mqtt: paho.Client | None = None
        self.config: InverterConfig | None = None
        self.discovery: HomeAssistantDiscovery | None = None

        # Write registers cache
        self._write_registers: list[dict[str, Any]] = []

    def setup(self) -> None:
        """Initialize all components and load configuration."""
        logger.info(f"Starting sofar2mqtt {self._get_version()}")

        # Load configuration
        self.config = load_config(self.config_path)

        # Cache write registers
        self._write_registers = [
            r.model_dump() for r in self.config.registers if r.write and not r.untested
        ]

        # Initialize Modbus client
        self.modbus = ModbusClient(device=self.modbus_device, retry=2, retry_delay=0.1)
        self.modbus.setup()

        # Initialize MQTT client
        client_id = f"sofar2mqtt-{socket.gethostname()}"
        self.mqtt = paho.Client(
            client_id=client_id,
            protocol=paho.MQTTv311,
        )

        if self.mqtt_user and self.mqtt_password:
            self.mqtt.username_pw_set(self.mqtt_user, self.mqtt_password)

        # Set up callbacks
        self.mqtt.on_connect = self._on_mqtt_connect
        self.mqtt.on_message = self._on_mqtt_message

        # Connect to MQTT
        self.mqtt.connect(self.mqtt_broker, self.mqtt_port)
        self.mqtt.loop_start()

        # Initialize discovery
        if self.ha_discovery:
            serial_number = self._get_serial_number()
            self.discovery = HomeAssistantDiscovery(self.mqtt, serial_number)

        logger.info(f"Setup complete for {self.device_name}")

    def start(self) -> None:
        """Start the client and main loop."""
        self.setup()

        def signal_handler(sig, frame):
            logger.info("Shutdown signal received")
            self.stop()

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        self.run()

    def _get_version(self) -> str:
        """Get package version."""
        try:
            from sofar2mqtt import __version__

            return __version__
        except ImportError:
            return "4.0.1"

    def _get_serial_number(self) -> str:
        """Get inverter serial number from config or use fallback."""
        # Check if serial_number register is defined in config
        if self.config:
            for register in self.config.registers:
                if register.name == "serial_number":
                    # If it's a static value, use that (even if wrong like ME3000SP)
                    if hasattr(register, "value") and register.value:
                        return str(register.value)
                    # Otherwise use fallback
                    break
        return "inverter"

    def _on_mqtt_connect(self, client, userdata, flags, rc, properties=None) -> None:
        """Handle MQTT connection."""
        logger.info(f"MQTT connected with result code {rc}")

        if rc == 0:
            # Subscribe to write topics
            self.mqtt.subscribe("sofar/rw/#", qos=0)

            # Publish Home Assistant discovery
            if self.discovery:
                self._publish_ha_discovery()

    def _on_mqtt_message(self, client, userdata, message) -> None:
        """Handle incoming MQTT messages (writes)."""
        topic = message.topic
        payload = message.payload.decode("utf-8")

        logger.debug(f"Received MQTT message on {topic}: {payload}")

        # Skip retained messages
        if message.retain:
            logger.info(f"Ignoring retained message on {topic}")
            return

        # Find matching write register
        for register in self._write_registers:
            if topic.endswith(f"/{register['name']}"):
                self._handle_register_write(register, payload)
                return

        logger.warning(f"No matching write register for topic: {topic}")

    def _handle_register_write(self, register: dict[str, Any], payload: str) -> None:
        """Handle write request for a register."""
        try:
            new_value = ValueConverter.to_raw(register, payload)

            # Validate value
            if not ValueConverter.validate(register, new_value):
                logger.error(f"Invalid value for {register['name']}: {payload}")
                return

            # Check mode-specific constraints
            if register["name"] == "desired_power":
                energy_mode = self.raw_data.get("energy_storage_mode")
                if int(energy_mode or 0) != 0:
                    logger.info("Cannot set desired_power - not in Passive mode")
                    return

            # Perform write with retry
            success = self._write_register(register, new_value)

            if success:
                logger.info(f"Successfully wrote {register['name']} = {payload}")
            else:
                logger.error(f"Failed to write {register['name']} = {payload}")

        except Exception as e:
            logger.error(f"Error handling write for {register['name']}: {e}")

    def _write_register(self, register: dict[str, Any], value: int) -> bool:
        """Write value to register with retry logic."""
        if not self.modbus:
            return False

        addr = int(register["register"], 16)

        # Special handling for multi-address registers
        if "write_addresses" in register:
            return self._write_special_register(register, value)

        # Standard write
        return self.modbus.write_register(addr, value)

    def _write_special_register(self, register: dict[str, Any], value: int) -> bool:
        """Handle special write operations (charge/discharge power)."""
        if not self.modbus:
            return False

        write_addr = register["write_addresses"].get("discharge")
        if not write_addr:
            logger.error("No write address found for special register")
            return False

        return self.modbus.write_register(int(write_addr, 16), abs(value))

    def update_state(self) -> None:
        """Read all registers and update state."""
        if not self.config or not self.modbus:
            logger.error("Not configured")
            return

        # Reset statistics per iteration
        self.requests = 0
        self.failures = 0
        self.retries = 0

        # Read all registers based on refresh interval
        for register in self.config.registers:
            if not register.read:
                continue

            refresh = register.refresh or 1
            if (self.iteration % refresh) != 0:
                logger.debug(f"Skipping {register.name} (refresh={refresh})")
                continue

            raw_value = self._read_register(register.model_dump())

            if raw_value is None:
                continue

            # Handle aggregate registers
            if register.aggregate:
                raw_value = combine_registers(self.raw_data, register.model_dump())
                if raw_value is None:
                    continue

            # Normalize sentinel values
            if isinstance(raw_value, int) and raw_value in (65535, -1):
                logger.debug(f"Normalizing sentinel value for {register.name}")
                raw_value = 0

            # Check for changes before publishing
            old_raw = self.raw_data.get(register.name)
            if register.notify_on_change and old_raw != raw_value:
                old_val = (
                    ValueConverter.from_raw(register.model_dump(), old_raw)
                    if old_raw is not None
                    else None
                )
                new_val = ValueConverter.from_raw(register.model_dump(), raw_value)
                logger.info(f"{register.name} changed: {old_val} → {new_val}")

            self.raw_data[register.name] = raw_value

        # Add Modbus statistics
        total = self.requests + self.retries
        failure_rate = round(self.failures / total * 100, 2) if total > 0 else 0.0
        retry_rate = round(self.retries / self.requests * 100, 2) if self.requests > 0 else 0.0

        self.raw_data["modbus_failures"] = self.failures
        self.raw_data["modbus_requests"] = self.requests
        self.raw_data["modbus_retries"] = self.retries
        self.raw_data["modbus_failure_rate"] = failure_rate
        self.raw_data["modbus_retry_rate"] = retry_rate

        logger.info(
            f"Modbus: req={self.requests} retries={self.retries} ({retry_rate}%) "
            f"failures={self.failures} ({failure_rate}%)"
        )

    def _read_register(self, register: dict[str, Any]) -> Any | None:
        """Read a single register."""
        if not self.modbus:
            return None

        read_type = register.get("read_type", "register")

        # Handle static values
        if read_type == "static":
            return register.get("value")

        # Handle string reads
        if read_type == "string":
            addr = int(register["register"], 16)
            num_regs = register.get("registers", 1)
            # Handle both int and list (from config parsing)
            if isinstance(num_regs, int):
                return self.modbus.read_string(addr, num_regs)
            else:
                return self.modbus.read_string(addr, len(num_regs))

        # Handle long reads
        if read_type == "long":
            addr = int(register["register"], 16)
            return self.modbus.read_long(addr, register.get("signed", False))

        # Standard register read
        addr = int(register["register"], 16)
        return self.modbus.read_register(addr, signed=register.get("signed", False))

    def publish_state(self) -> None:
        """Publish all state to MQTT."""
        if not self.mqtt or not self.config:
            return

        # Build state dictionary with normalized values
        data = {}
        for register in self.config.registers:
            name = register.name
            if name in self.raw_data:
                raw_value = self.raw_data[name]
                normalized = ValueConverter.from_raw(register.model_dump(), raw_value)
                data[name] = normalized

        # Publish aggregated state
        json_data = json.dumps(data, indent=2)
        self.mqtt.publish("sofar/state_all", json_data, retain=True)

        # Legacy individual publishing
        for register in self.config.registers:
            name = register.name
            if name in self.raw_data:
                value = ValueConverter.from_raw(register.model_dump(), self.raw_data[name])
                self.mqtt.publish(f"sofar/{name}", value, retain=False)

        # Wait for refresh interval
        time.sleep(self.poll_interval)

    def _publish_ha_discovery(self) -> None:
        """Publish Home Assistant auto-discovery configurations."""
        if not self.discovery or not self.config:
            return

        # Wait for version info to be available
        while self.raw_data.get("sw_version_com") in [None, "TBD"] and self.raw_data.get(
            "hw_version"
        ) in [None, "TBD"]:
            logger.info("Waiting for version info...")
            time.sleep(5)

        # Discover all registers
        self.discovery.discover_all(self.config.registers, self.device_id, self.device_name)

    def run(self) -> None:
        """Main execution loop."""
        self.running = True

        # Initial read
        self.update_state()
        self.publish_state()

        # Main loop
        while self.running:
            try:
                # Keep MQTT alive
                self.mqtt.publish("sofar2mqtt_python/bridge", "online", retain=False)

                # Read and publish
                self.update_state()
                self.publish_state()

                self.iteration += 1

            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                time.sleep(5)

    def stop(self) -> None:
        """Gracefully shutdown."""
        logger.info("Shutting down...")
        self.running = False

        # Publish offline status
        if self.mqtt:
            self.mqtt.publish("sofar2mqtt_python/bridge", "offline", retain=False)
            self.mqtt.disconnect()
            self.mqtt.loop_stop()

        # Close Modbus
        if self.modbus:
            self.modbus.close()
