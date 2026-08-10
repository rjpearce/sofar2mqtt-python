"""Main Sofar client orchestrating all components."""

import json
import logging
import signal
import socket
import time
from threading import Lock
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
        modbus_baudrate: int = 9600,
        modbus_parity: str = "N",
        mqtt_host: str = "localhost",
        mqtt_port: int = 1883,
        mqtt_user: str | None = None,
        mqtt_password: str | None = None,
        device_id: str = "sofar",
        device_name: str = "Sofar Inverter",
        poll_interval: int = 10,
        ha_discovery: bool = True,
    ):
        """Initialize Sofar client with all dependencies."""
        self.config_path = config_path
        self.modbus_device = modbus_device
        self.modbus_baudrate = modbus_baudrate
        self.modbus_parity = modbus_parity
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port
        self.mqtt_user = mqtt_user
        self.mqtt_password = mqtt_password
        self.device_id = device_id
        self.device_name = device_name
        self.poll_interval = poll_interval
        self.ha_discovery = ha_discovery

        # Core components
        self.config: InverterConfig | None = None
        self.modbus: ModbusClient | None = None
        self.mqtt: paho.Client | None = None
        self.discovery: HomeAssistantDiscovery | None = None

        # State
        self.raw_data: dict[str, Any] = {}
        self.failures: int = 0
        self.iteration: int = 0
        self.running: bool = False
        self._lock = Lock()
        self._write_registers: list[dict[str, Any]] = []
        self._last_heartbeat: float = 0.0

    def setup(self) -> None:
        """Initialize all components and load configuration."""
        logger.info(f"Starting sofar2mqtt {self._get_version()}")

        # Load configuration
        self.config = load_config(self.config_path)
        if not self.config:
            raise RuntimeError("Failed to load configuration")

        # Validate write register blocks
        for i, block in enumerate(self.config.write_register_blocks or []):
            if block is None:
                logger.error(f"Write register block {i} is None!")
                continue

        # Initialize Modbus
        self.modbus = ModbusClient(
            device=self.modbus_device,
        )
        self.modbus.setup()

        # Initialize MQTT client
        client_id = f"sofar2mqtt_{socket.gethostname()}_{self.device_id}"
        self.mqtt = paho.Client(
            client_id=client_id,
            userdata=self,
            protocol=paho.MQTTv311,
        )
        self.mqtt.enable_logger(logger)

        # Set LWT
        self.mqtt.will_set(
            "sofar2mqtt_python/bridge",
            payload="offline",
            qos=1,
            retain=True,
        )

        # Connect to MQTT
        if self.mqtt_user and self.mqtt_password:
            self.mqtt.username_pw_set(self.mqtt_user, self.mqtt_password)

        # Set up MQTT callbacks (subscribe/discovery happen in on_connect so they
        # only run once the connection is established, and again on reconnect)
        self.mqtt.on_connect = self._on_mqtt_connect
        self.mqtt.on_message = self.handle_write

        self.mqtt.connect(self.mqtt_host, self.mqtt_port, keepalive=60)
        self.mqtt.loop_start()

        # Initialize Home Assistant discovery
        if self.ha_discovery:
            self.discovery = HomeAssistantDiscovery(
                mqtt_client=self.mqtt,
                serial_number=self.device_id,
            )

        logger.info(f"Setup complete for {self.device_name}")

    def _on_mqtt_connect(self, client, userdata, flags, rc, properties=None) -> None:
        """Handle MQTT connection: subscribe to write topics and publish discovery."""
        logger.info(f"MQTT connected with result code {rc}")
        if rc != 0:
            return

        client.subscribe("sofar/rw/#", qos=1)
        logger.info("Subscribed to write topics: sofar/rw/#")

        if self.discovery:
            self._publish_ha_discovery()

    def start(self) -> None:
        """Start the client and main loop."""
        self.setup()

        def signal_handler(sig, frame):
            logger.info("Received shutdown signal")
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
            return "unknown"

    def handle_write(self, client: paho.Client, userdata: Any, message: paho.MQTTMessage) -> None:
        """Handle incoming MQTT messages for write operations."""
        if not self.config:
            logger.error("Not configured")
            return

        topic = message.topic
        payload = message.payload.decode()

        # Skip retained messages to avoid re-applying stale commands on startup
        if message.retain:
            logger.info(f"Ignoring retained message on {topic}")
            return

        # Parse topic to find register
        parts = topic.split("/")
        if len(parts) < 2:
            logger.error(f"Invalid topic format: {topic}")
            return

        register_name = parts[-1]
        register = next((r for r in self.config.registers if r.name == register_name), None)

        if not register:
            logger.error(f"Register not found: {register_name}")
            return

        if not register.write or register.untested:
            logger.error(f"Register is not writable: {register_name}")
            return

        try:
            logger.debug(f"Handling write for register: {register}, payload: {payload}")

            # Convert payload using the register's conversion function
            # This handles mode functions (e.g., "Passive mode" -> 3) and other transformations
            register_dict = register.model_dump()
            new_value = ValueConverter.to_raw(register_dict, payload)

            # Validate value
            logger.debug(f"Validating register={register.name}, new_value={new_value}")
            if not ValueConverter.validate(register_dict, new_value):
                logger.error(f"Invalid value for {register.name}: {payload}")
                return

            # Passive registers (e.g. charge_discharge_power) are only
            # accepted while the inverter is in Passive mode
            if register.passive and not self._is_passive_mode():
                logger.info(
                    f"Received a request for {register.name} but not in Passive mode. Ignoring"
                )
                return

            # Queue write operation
            with self._lock:
                self._write_registers.append(
                    {
                        "register": register.model_dump(),
                        "value": new_value,
                    }
                )
            logger.info(f"Queued write for {register.name}: {new_value}")

        except (ValueError, TypeError):
            logger.error(f"Invalid payload format: {payload}")

    def _is_passive_mode(self) -> bool:
        """Check if the inverter's working mode is currently Passive mode."""
        if not self.config:
            return False
        for register in self.config.registers:
            if register.function != "mode" or not register.modes:
                continue
            for key, label in register.modes.items():
                if label == "Passive mode":
                    raw_value = self.raw_data.get(register.name)
                    return raw_value is not None and int(raw_value) == int(key)
        return False

    def _send_heartbeat(self) -> None:
        """Send a passive-mode heartbeat to the inverter."""
        if not self.config or not self.config.heartbeat or not self.config.heartbeat.enabled:
            return
        heartbeat = self.config.heartbeat
        if not self.modbus:
            return

        try:
            logger.debug(
                f"Sending heartbeat to {heartbeat.address} "
                f"(fc {heartbeat.function_code}, value {heartbeat.value})"
            )
            result = self.modbus.write_register_special(
                int(heartbeat.address, 16),
                heartbeat.function_code,
                int(heartbeat.value, 16),
            )
            self._last_heartbeat = time.time()
            if result is not None:
                logger.debug(f"Heartbeat response: {result.hex(' ')}")
            else:
                logger.warning(f"Heartbeat to {heartbeat.address} got no response")
        except Exception as e:
            logger.error(f"Failed to send heartbeat: {e}")

    def _write_register(self, register: dict[str, Any], value: float) -> None:
        """Write a single register."""
        if not self.modbus:
            logger.error("Modbus client not initialized")
            return

        try:
            write_addr = register.get("register")

            # ME3000SP passive power uses proprietary function 0x42 and a
            # different address for charge and discharge.
            write_addresses = register.get("write_addresses")
            if write_addresses:
                power = int(value)
                if power == 0:
                    address_key = "standby"
                    write_value = int((register.get("write_values") or {}).get("standby", 0x5555))
                elif power > 0:
                    address_key = "charge"
                    write_value = power
                else:
                    address_key = "discharge"
                    write_value = abs(power)

                address = write_addresses.get(address_key)
                if not address:
                    logger.error(f"No {address_key} address for {register.get('name')}")
                    return

                function_code = int(register.get("write_functioncode", 66))
                logger.info(
                    f"Writing {register['name']}={write_value} to address {address} "
                    f"({address_key}) using special function code {function_code}"
                )
                result = self.modbus.write_register_special(
                    int(address, 16), function_code, write_value
                )
                if result is None:
                    logger.error(f"Failed passive write for {register.get('name')}")
                else:
                    logger.debug(
                        f"Passive write response for {register.get('name')}: {result.hex(' ')}"
                    )
                return

            if not write_addr:
                logger.error(f"No address for register {register.get('name')}")
                return

            # Handle signed values
            if register.get("signed", False) and value < 0:
                value = 65536 + value

            write_type = register.get("write_type", "standard")
            abs_value = int(abs(value))

            if write_type == "special":
                # Use a special/proprietary function code (e.g., 66) for this write
                function_code = int(register.get("write_functioncode", 66))
                logger.info(
                    f"Writing {register['name']}={abs_value} to address {write_addr} "
                    f"using special function code {function_code}"
                )
                result = self.modbus.write_register_special(
                    int(write_addr, 16), function_code, abs_value
                )
                if result is None:
                    logger.error(f"Failed to write {register.get('name')} (special write)")
            else:
                # Use standard function code 6
                logger.info(f"Writing {register['name']}={abs_value} to address {write_addr}")
                success = self.modbus.write_register(int(write_addr, 16), abs_value)
                if not success:
                    logger.error(f"Failed to write {register.get('name')}")

        except Exception as e:
            logger.error(f"Failed to write {register.get('name')}: {e}")

    def update_state(self) -> None:
        """Read all registers and update state."""
        if not self.config or not self.modbus:
            logger.error("Not configured")
            return

        # Process pending writes
        with self._lock:
            writes_to_process = self._write_registers.copy()
            self._write_registers.clear()

        for write_item in writes_to_process:
            self._write_register(write_item["register"], write_item["value"])

        # Read all registers based on their refresh interval
        for register in self.config.registers:
            if not register.read:
                continue

            refresh = register.refresh or 1
            if (self.iteration % refresh) != 0:
                logger.debug(f"Skipping {register.name} (refresh={refresh})")
                continue

            reg_dict = register.model_dump()

            # Aggregate registers are computed from other registers' values
            # and have no Modbus address to read
            if register.aggregate:
                raw_value = combine_registers(self.raw_data, reg_dict)
                if raw_value is None:
                    continue
            else:
                raw_value = self._read_register(reg_dict)
                if raw_value is None:
                    # Static registers always have a value; None here means a read failure
                    if reg_dict.get("read_type") != "static":
                        self.failures += 1
                    continue

            # Normalize sentinel values (invalid/placeholder readings)
            if isinstance(raw_value, int) and raw_value in (65535, -1, register.sentinel_value):
                logger.debug(f"Normalizing sentinel value for {register.name}")
                raw_value = 0

            # Log changes for registers marked notify_on_change
            old_raw = self.raw_data.get(register.name)
            if register.notify_on_change and old_raw != raw_value:
                old_val = (
                    ValueConverter.from_raw(reg_dict, old_raw) if old_raw is not None else None
                )
                new_val = ValueConverter.from_raw(reg_dict, raw_value)
                logger.info(f"{register.name} changed: {old_val} → {new_val}")

            self.raw_data[register.name] = raw_value

        # Update statistics
        self._update_statistics()

    def _update_statistics(self) -> None:
        """Update connection statistics."""
        self.raw_data["modbus_failures"] = self.failures
        self.raw_data["modbus_iterations"] = self.iteration

        if self.iteration > 0:
            failure_rate = (self.failures / self.iteration) * 100
            self.raw_data["modbus_retry_rate"] = failure_rate

            logger.debug(
                f"failures={self.failures} ({failure_rate:.1f}%)",
            )

    def _read_register(self, register: dict[str, Any]) -> Any | None:
        """Read a single register and return its raw (unconverted) value."""
        if not self.modbus:
            return None

        read_type = register.get("read_type", "register")

        # Handle static values (not read from Modbus)
        if read_type == "static":
            return register.get("value")

        addr = register.get("register")
        if not addr:
            logger.debug(f"No address for register {register.get('name')}, skipping")
            return None

        try:
            # Handle string reads
            if read_type == "string":
                num_regs = register.get("registers", 1)
                # Handle both int and list (from config parsing)
                count = num_regs if isinstance(num_regs, int) else len(num_regs)
                return self.modbus.read_string(int(addr, 16), count)

            # Handle long (32-bit) reads
            if read_type == "long":
                return self.modbus.read_long(int(addr, 16), register.get("signed", False))

            # Standard single register read
            return self.modbus.read_register(int(addr, 16), signed=register.get("signed", False))

        except Exception as e:
            logger.error(f"Failed to read {register.get('name')}: {e}")
            return None

    def publish_state(self) -> None:
        """Publish all state to MQTT."""
        if not self.mqtt or not self.config:
            return

        # Build state dictionary with normalized (converted) values
        data: dict[str, Any] = {
            "device": self.device_name,
            "device_id": self.device_id,
            "timestamp": time.time(),
        }
        for register in self.config.registers:
            if register.name in self.raw_data:
                data[register.name] = ValueConverter.from_raw(
                    register.model_dump(), self.raw_data[register.name]
                )

        # Publish aggregated state
        json_data = json.dumps(data, indent=2)
        self.mqtt.publish("sofar/state_all", json_data, retain=True)

        # Legacy individual publishing
        for register in self.config.registers:
            if register.name in data:
                self.mqtt.publish(f"sofar/{register.name}", data[register.name], retain=False)

    def _publish_ha_discovery(self) -> None:
        """Publish Home Assistant auto-discovery configurations."""
        if not self.discovery or not self.config:
            return

        # Discover all registers
        self.discovery.discover_all(self.config.registers, self.device_id, self.device_name)

    def _maybe_heartbeat(self) -> None:
        """Send a heartbeat if Passive mode is active and the interval has elapsed."""
        if not self.config or not self.config.heartbeat or not self.config.heartbeat.enabled:
            return
        if not self._is_passive_mode():
            self._last_heartbeat = time.time()
            return
        interval = self.config.heartbeat.interval
        if time.time() - self._last_heartbeat >= interval:
            self._send_heartbeat()

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

                # Send passive-mode heartbeat if required
                self._maybe_heartbeat()

                # Read and publish
                self.update_state()
                self.publish_state()

                self.iteration += 1

                # Wait for next poll interval
                time.sleep(self.poll_interval)

            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                time.sleep(5)

    def stop(self) -> None:
        """Gracefully shutdown."""
        logger.info("Shutting down...")
        self.running = False

        # Publish offline status (before LWT takes over on disconnect)
        if self.mqtt:
            # Clear the will to prevent duplicate offline messages
            self.mqtt.will_clear()
            self.mqtt.publish("sofar2mqtt_python/bridge", "offline", retain=True)
            self.mqtt.disconnect()
            self.mqtt.loop_stop()

        # Close Modbus
        if self.modbus:
            self.modbus.close()
