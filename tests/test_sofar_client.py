"""Tests for the main Sofar client orchestrator."""

import json
import time
from unittest.mock import MagicMock, patch

import pytest

from sofar2mqtt.core.sofar_client import SofarClient
from sofar2mqtt.models.inverter_config import InverterConfig


def make_config(registers, heartbeat=None):
    """Build a real InverterConfig from a register list."""
    data = {"registers": registers}
    if heartbeat is not None:
        data["heartbeat"] = heartbeat
    return InverterConfig.from_dict(data)


def make_client(config) -> SofarClient:
    """Create a SofarClient with all external dependencies mocked."""
    with (
        patch("sofar2mqtt.core.sofar_client.load_config", return_value=config),
        patch("sofar2mqtt.core.sofar_client.ModbusClient"),
        patch("sofar2mqtt.core.sofar_client.paho.Client"),
        patch("sofar2mqtt.core.sofar_client.HomeAssistantDiscovery"),
    ):
        client = SofarClient(
            config_path="test.json",
            modbus_device="/dev/ttyUSB0",
            mqtt_host="localhost",
            device_id="test_device",
            device_name="Test Inverter",
        )
        client.setup()
    return client


def make_message(topic: str, payload: str, retain: bool = False) -> MagicMock:
    """Create a mock MQTT message."""
    message = MagicMock()
    message.topic = topic
    message.payload = payload.encode()
    message.retain = retain
    return message


@pytest.fixture
def client():
    """Client with a read register, a writable register, and a static register."""
    config = make_config(
        [
            {
                "name": "test_register",
                "register": "0x0100",
                "function": "divide",
                "factor": 10,
            },
            {
                "name": "test_write",
                "register": "0x0200",
                "write": True,
                "min": 0,
                "max": 5000,
            },
            {
                "name": "static_register",
                "read_type": "static",
                "value": "static-value",
            },
        ]
    )
    return make_client(config)


class TestSofarClient:
    """Tests for SofarClient class."""

    def test_initialization(self, client):
        """Test client initialization."""
        assert client.device_id == "test_device"
        assert client.device_name == "Test Inverter"
        assert client.poll_interval == 10
        assert client.running is False

    def test_setup(self, client):
        """Test setup method wires up all components."""
        assert client.config is not None
        assert client.modbus is not None
        assert client.mqtt is not None
        client.modbus.setup.assert_called_once()
        client.mqtt.connect.assert_called_once_with("localhost", 1883, keepalive=60)
        client.mqtt.loop_start.assert_called_once()
        assert client.mqtt.on_message == client.handle_write

    def test_on_mqtt_connect_subscribes_and_discovers(self, client):
        """Test on_connect subscribes to write topics and publishes discovery."""
        client._on_mqtt_connect(client.mqtt, None, {}, 0)

        client.mqtt.subscribe.assert_called_once_with("sofar/rw/#", qos=1)
        client.discovery.discover_all.assert_called_once()

    def test_on_mqtt_connect_error_does_nothing(self, client):
        """Test on_connect with error code does not subscribe."""
        client._on_mqtt_connect(client.mqtt, None, {}, 1)
        client.mqtt.subscribe.assert_not_called()

    def test_handle_write_invalid_topic(self, client):
        """Test handling invalid topic format."""
        client.handle_write(client.mqtt, None, make_message("invalid", "100"))
        assert client._write_registers == []

    def test_handle_write_register_not_found(self, client):
        """Test handling write for non-existent register."""
        client.handle_write(client.mqtt, None, make_message("sofar/rw/nonexistent", "100"))
        assert client._write_registers == []

    def test_handle_write_retained_message_ignored(self, client):
        """Test retained write commands are ignored."""
        client.handle_write(
            client.mqtt, None, make_message("sofar/rw/test_write", "100", retain=True)
        )
        assert client._write_registers == []

    def test_handle_write_readonly_register_rejected(self, client):
        """Test writes to read-only registers are rejected."""
        client.handle_write(client.mqtt, None, make_message("sofar/rw/test_register", "100"))
        assert client._write_registers == []

    def test_handle_write_success_queues_write(self, client):
        """Test successful write operation is queued."""
        client.handle_write(client.mqtt, None, make_message("sofar/rw/test_write", "100"))

        assert len(client._write_registers) == 1
        assert client._write_registers[0]["register"]["name"] == "test_write"
        assert client._write_registers[0]["value"] == 100

    def test_handle_write_out_of_range_rejected(self, client):
        """Test values outside min/max are rejected."""
        client.handle_write(client.mqtt, None, make_message("sofar/rw/test_write", "99999"))
        assert client._write_registers == []

    def test_handle_write_invalid_payload_rejected(self, client):
        """Test non-numeric payloads are rejected."""
        client.handle_write(client.mqtt, None, make_message("sofar/rw/test_write", "abc"))
        assert client._write_registers == []

    def test_update_state_reads_registers(self, client):
        """Test state update stores raw register values."""
        client.modbus.read_register = MagicMock(return_value=235)

        client.update_state()

        assert client.raw_data["test_register"] == 235
        assert client.raw_data["static_register"] == "static-value"

    def test_update_state_processes_queued_writes(self, client):
        """Test queued writes are processed at the start of update_state."""
        client.modbus.read_register = MagicMock(return_value=1)
        client.modbus.write_register = MagicMock(return_value=True)
        client.handle_write(client.mqtt, None, make_message("sofar/rw/test_write", "100"))

        client.update_state()

        client.modbus.write_register.assert_called_once_with(0x0200, 100)
        assert client._write_registers == []

    def test_update_state_counts_failures(self, client):
        """Test read failures are counted."""
        client.modbus.read_register = MagicMock(return_value=None)

        client.update_state()

        assert client.failures > 0

    def test_update_state_respects_refresh_interval(self):
        """Test registers are skipped between refresh intervals."""
        config = make_config([{"name": "slow_register", "register": "0x0100", "refresh": 5}])
        client = make_client(config)
        client.modbus.read_register = MagicMock(return_value=42)

        client.iteration = 1  # 1 % 5 != 0 -> skipped
        client.update_state()
        assert "slow_register" not in client.raw_data

        client.iteration = 5  # 5 % 5 == 0 -> read
        client.update_state()
        assert client.raw_data["slow_register"] == 42

    def test_update_state_normalizes_sentinel_values(self):
        """Test sentinel values are normalized to 0."""
        config = make_config([{"name": "test_register", "register": "0x0100"}])
        client = make_client(config)
        client.modbus.read_register = MagicMock(return_value=65535)

        client.update_state()

        assert client.raw_data["test_register"] == 0

    def test_update_state_aggregate_registers(self):
        """Test aggregate registers are combined from other registers."""
        config = make_config(
            [
                {"name": "pv_1_power", "register": "0x0300"},
                {"name": "pv_2_power", "register": "0x0301"},
                {
                    "name": "pv_total_power",
                    "aggregate": ["pv_1_power", "pv_2_power"],
                    "agg_function": "add",
                },
            ]
        )
        client = make_client(config)
        client.modbus.read_register = MagicMock(
            side_effect=lambda addr, **kwargs: 10 if addr == 0x0300 else 20
        )

        client.update_state()

        assert client.raw_data["pv_total_power"] == 30

    def test_publish_state_converts_values_once(self, client):
        """Test published state contains converted (not raw) values."""
        client.raw_data = {"test_register": 235}

        client.publish_state()

        # First publish call is the aggregated JSON state
        args, kwargs = client.mqtt.publish.call_args_list[0]
        assert args[0] == "sofar/state_all"
        state = json.loads(args[1])
        assert state["test_register"] == 23.5

    def test_passive_write_blocked_when_not_in_passive_mode(self):
        """Test passive registers are rejected unless the inverter is in Passive mode."""
        config = make_config(
            [
                {
                    "name": "working_mode",
                    "register": "0x1200",
                    "function": "mode",
                    "modes": {"0": "Auto", "3": "Passive mode"},
                },
                {
                    "name": "charge_discharge_power",
                    "write": True,
                    "read": False,
                    "function": "int",
                    "min": -3000,
                    "max": 3000,
                    "passive": True,
                },
            ]
        )
        client = make_client(config)
        client.raw_data["working_mode"] = 0  # Auto

        client.handle_write(
            client.mqtt, None, make_message("sofar/rw/charge_discharge_power", "100")
        )
        assert client._write_registers == []

        client.raw_data["working_mode"] = 3  # Passive mode
        client.handle_write(
            client.mqtt, None, make_message("sofar/rw/charge_discharge_power", "100")
        )
        assert len(client._write_registers) == 1

    def test_working_mode_write_uses_standard_function_code(self):
        """Test working_mode writes use a standard FC6 register write."""
        config = make_config(
            [
                {
                    "name": "working_mode",
                    "register": "0x1200",
                    "write": True,
                    "function": "mode",
                    "modes": {"0": "Auto", "3": "Passive mode"},
                }
            ]
        )
        client = make_client(config)

        message = make_message("sofar/rw/working_mode", "Passive mode")
        client.handle_write(client.mqtt, None, message)
        assert client._write_registers[0]["value"] == 3

        client.update_state()
        client.modbus.write_register.assert_called_once_with(0x1200, 3)

    def test_special_write_uses_function_code(self):
        """Test special write_type uses write_register_special."""
        config = make_config(
            [
                {
                    "name": "special_register",
                    "register": "0x1200",
                    "write": True,
                    "write_type": "special",
                    "write_functioncode": "66",
                    "function": "mode",
                    "modes": {"0": "Auto", "3": "Passive mode"},
                }
            ]
        )
        client = make_client(config)

        message = make_message("sofar/rw/special_register", "Passive mode")
        client.handle_write(client.mqtt, None, message)
        assert client._write_registers[0]["value"] == 3

        client.update_state()
        client.modbus.write_register_special.assert_called_once_with(0x1200, 66, 3)

    def test_passive_power_write_selects_charge_or_discharge_address(self):
        """Test ME3000SP passive power writes use the signed address mapping."""
        config = make_config(
            [
                {
                    "name": "working_mode",
                    "register": "0x1200",
                    "function": "mode",
                    "modes": {"0": "Auto", "3": "Passive mode"},
                },
                {
                    "name": "charge_discharge_power",
                    "write": True,
                    "read": False,
                    "function": "int",
                    "min": -3000,
                    "max": 3000,
                    "passive": True,
                    "write_functioncode": "66",
                    "write_addresses": {
                        "standby": "0x0100",
                        "discharge": "0x0101",
                        "charge": "0x0102",
                    },
                },
            ]
        )
        client = make_client(config)
        client.raw_data["working_mode"] = 3  # Passive mode
        client.modbus.read_register = MagicMock(return_value=3)  # stays in Passive mode

        client.handle_write(
            client.mqtt,
            None,
            make_message("sofar/rw/charge_discharge_power", "500"),
        )
        client.update_state()
        client.modbus.write_register_special.assert_called_once_with(0x0102, 66, 500)

        client.modbus.write_register_special.reset_mock()
        client.handle_write(
            client.mqtt,
            None,
            make_message("sofar/rw/charge_discharge_power", "-500"),
        )
        client.update_state()
        client.modbus.write_register_special.assert_called_once_with(0x0101, 66, 500)

    def test_heartbeat_sent_when_in_passive_mode(self):
        """Test heartbeat is sent at interval while in Passive mode."""
        config = make_config(
            [
                {
                    "name": "working_mode",
                    "register": "0x1200",
                    "function": "mode",
                    "modes": {"0": "Auto", "3": "Passive mode"},
                }
            ],
            heartbeat={"address": "0x2201", "value": "0x2202", "function_code": 73, "interval": 5},
        )
        client = make_client(config)
        client.raw_data["working_mode"] = 3  # Passive mode
        client._last_heartbeat = time.time() - 6  # interval elapsed

        client._maybe_heartbeat()

        client.modbus.write_register_special.assert_called_once_with(0x2201, 73, 0x2202)

    def test_heartbeat_skipped_when_not_in_passive_mode(self):
        """Test heartbeat is not sent outside Passive mode."""
        config = make_config(
            [
                {
                    "name": "working_mode",
                    "register": "0x1200",
                    "function": "mode",
                    "modes": {"0": "Auto", "3": "Passive mode"},
                }
            ],
            heartbeat={"address": "0x2201", "value": "0x2202", "function_code": 73, "interval": 5},
        )
        client = make_client(config)
        client.raw_data["working_mode"] = 0  # Auto
        client._last_heartbeat = time.time() - 6

        client._maybe_heartbeat()

        client.modbus.write_register_special.assert_not_called()

    def test_heartbeat_skipped_within_interval(self):
        """Test heartbeat is not sent before the interval elapses."""
        config = make_config(
            [
                {
                    "name": "working_mode",
                    "register": "0x1200",
                    "function": "mode",
                    "modes": {"0": "Auto", "3": "Passive mode"},
                }
            ],
            heartbeat={"interval": 10},
        )
        client = make_client(config)
        client.raw_data["working_mode"] = 3  # Passive mode
        client._last_heartbeat = time.time() - 5

        client._maybe_heartbeat()

        client.modbus.write_register_special.assert_not_called()

    def test_stop(self, client):
        """Test graceful shutdown."""
        client.running = True

        client.stop()

        assert client.running is False
        assert client.mqtt.disconnect.called
        assert client.modbus.close.called

    def test_version_detection(self, client):
        """Test version detection."""
        version = client._get_version()
        assert isinstance(version, str)

    def test_statistics_update(self, client):
        """Test statistics update."""
        client.iteration = 10
        client.failures = 2

        client._update_statistics()

        assert client.raw_data["modbus_failures"] == 2
        assert client.raw_data["modbus_iterations"] == 10
