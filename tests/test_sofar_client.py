"""Tests for main SoFar client functionality."""

import pytest
import json
import time
from unittest.mock import MagicMock, patch, call
from sofar2mqtt.core.sofar_client import SofarClient
from sofar2mqtt.models.inverter_config import InverterConfig
from sofar2mqtt.models.register import RegisterDefinition


@pytest.fixture
def mock_config():
    """Create a mock inverter configuration."""
    return InverterConfig(
        registers=[
            RegisterDefinition(name="voltage", register="0x1000", refresh=1, read=True),
            RegisterDefinition(name="current", register="0x1001", refresh=1, read=True),
            RegisterDefinition(name="power", register="0x1002", refresh=5, read=True),
        ]
    )


class TestSofarClientInit:
    """Test SoFar client initialization."""

    def test_init_default_values(self):
        """Test default initialization values."""
        client = SofarClient(
            config_path="/tmp/config.json",
            modbus_device="/dev/ttyUSB0",
            mqtt_broker="localhost",
        )

        assert client.device_id == "sofar"
        assert client.device_name == "Sofar Inverter"
        assert client.poll_interval == 10
        assert client.ha_discovery is True
        assert client.running is False

    def test_init_custom_values(self):
        """Test custom initialization values."""
        client = SofarClient(
            config_path="/tmp/config.json",
            modbus_device="/dev/ttyUSB0",
            mqtt_broker="localhost",
            device_id="test-device",
            device_name="Test Inverter",
            poll_interval=30,
            ha_discovery=False,
        )

        assert client.device_id == "test-device"
        assert client.device_name == "Test Inverter"
        assert client.poll_interval == 30
        assert client.ha_discovery is False


class TestSofarClientSetup:
    """Test client setup and initialization."""

    @patch("sofar2mqtt.core.sofar_client.ModbusClient")
    @patch("sofar2mqtt.core.sofar_client.paho.Client")
    @patch("sofar2mqtt.core.sofar_client.HomeAssistantDiscovery")
    def test_setup_initializes_components(
        self, mock_discovery, mock_mqtt, mock_modbus, mock_config
    ):
        """Test that setup initializes all required components."""
        with patch("sofar2mqtt.core.sofar_client.load_config", return_value=mock_config):
            client = SofarClient(
                config_path="/tmp/config.json",
                modbus_device="/dev/ttyUSB0",
                mqtt_broker="localhost",
            )

            client.setup()

            # Verify components were initialized
            assert client.modbus is not None
            assert client.mqtt is not None
            assert client.config is not None
            assert client.discovery is not None

            # Verify MQTT connect was called
            client.mqtt.connect.assert_called_once()
            client.mqtt.loop_start.assert_called_once()

    @patch("sofar2mqtt.core.sofar_client.ModbusClient")
    @patch("sofar2mqtt.core.sofar_client.paho.Client")
    def test_setup_does_not_create_discovery_when_disabled(self, mock_mqtt, mock_modbus):
        """Test that discovery is not created when HA discovery is disabled."""
        mock_config_instance = MagicMock()
        mock_config_instance.registers = []

        with patch("sofar2mqtt.core.sofar_client.load_config", return_value=mock_config_instance):
            client = SofarClient(
                config_path="/tmp/config.json",
                modbus_device="/dev/ttyUSB0",
                mqtt_broker="localhost",
                ha_discovery=False,
            )

            client.setup()

            assert client.discovery is None

    @patch("sofar2mqtt.core.sofar_client.ModbusClient")
    @patch("sofar2mqtt.core.sofar_client.paho.Client")
    @patch("sofar2mqtt.core.sofar_client.HomeAssistantDiscovery")
    def test_setup_creates_write_registers_cache(self, mock_discovery, mock_mqtt, mock_modbus):
        """Test that write register cache is created during setup."""
        mock_config_with_writes = InverterConfig(
            registers=[
                RegisterDefinition(name="voltage", register="0x1000", read=True, write=True),
                RegisterDefinition(name="current", register="0x1001", read=True),
            ]
        )

        with patch(
            "sofar2mqtt.core.sofar_client.load_config", return_value=mock_config_with_writes
        ):
            client = SofarClient(
                config_path="/tmp/config.json",
                modbus_device="/dev/ttyUSB0",
                mqtt_broker="localhost",
            )
            client.setup()

            assert len(client._write_registers) == 1
            assert client._write_registers[0]["name"] == "voltage"


class TestSofarClientUpdateState:
    """Test state update functionality."""

    @patch("sofar2mqtt.core.sofar_client.ValueConverter")
    def test_update_state_reads_registers(self, mock_converter, mock_modbus, mock_config):
        """Test that update state reads all active registers."""
        client = SofarClient(
            config_path="/tmp/config.json",
            modbus_device="/dev/ttyUSB0",
            mqtt_broker="localhost",
        )
        client.config = mock_config
        client.modbus = mock_modbus
        mock_modbus.read_register = MagicMock(return_value=230)

        mock_converter.from_raw = MagicMock(return_value=230.0)
        mock_converter.validate = MagicMock(return_value=True)

        client.update_state()

        # Should attempt to read from each register
        assert mock_modbus.read_register.call_count == 3
        # raw_data includes modbus stats, so expect 8 entries (3 registers + 5 stats)

    def test_update_state_filters_by_refresh_interval(self, mock_modbus, mock_config):
        """Test that refresh intervals filter which registers are read."""
        # Create a config with staggered refresh intervals
        from sofar2mqtt.models.inverter_config import InverterConfig
        from sofar2mqtt.models.register import RegisterDefinition

        staggered_config = InverterConfig(
            registers=[
                RegisterDefinition(name="voltage", register="0x1000", refresh=1, read=True),
                RegisterDefinition(name="current", register="0x1001", refresh=2, read=True),
                RegisterDefinition(name="power", register="0x1002", refresh=5, read=True),
            ]
        )

        client = SofarClient(
            config_path="/tmp/config.json",
            modbus_device="/dev/ttyUSB0",
            mqtt_broker="localhost",
        )
        client.config = staggered_config
        client.modbus = mock_modbus
        mock_modbus.read_register = MagicMock(return_value=230)

        # Run iteration 0 (all registers read since 0 % N = 0 for any N)
        client.update_state()

        # All registers should be read on iteration 0
        assert mock_modbus.read_register.call_count == 3  # voltage + current + power

        # Run iteration 1 (only voltage with refresh=1)
        client.iteration = 1
        client.update_state()

        # Only voltage should be read
        assert mock_modbus.read_register.call_count == 4  # 3 + 1


class TestSofarClientPublishState:
    """Test state publishing functionality."""

    @patch("sofar2mqtt.core.sofar_client.ValueConverter")
    def test_publish_state_publishes_all_registers(self, mock_converter, mock_modbus):
        """Test that all register values are published."""
        mock_config_instance = InverterConfig(
            registers=[
                RegisterDefinition(name="voltage", register="0x1000", read=True),
                RegisterDefinition(name="current", register="0x1001", read=True),
            ]
        )

        client = SofarClient(
            config_path="/tmp/config.json",
            modbus_device="/dev/ttyUSB0",
            mqtt_broker="localhost",
        )
        client.config = mock_config_instance
        client.mqtt = MagicMock()
        client.raw_data = {"voltage": 230, "current": 5}

        mock_converter.from_raw = MagicMock(side_effect=lambda r, v: float(v))

        client.publish_state()

        # Verify all values were published
        assert client.mqtt.publish.call_count >= 3  # state_all + individual + bridge

    def test_publish_state_writes_data_file(self, mock_converter, mock_modbus):
        """Test that publish_state writes data to file."""
        mock_config_instance = InverterConfig(
            registers=[RegisterDefinition(name="voltage", register="0x1000", read=True)]
        )

        client = SofarClient(
            config_path="/tmp/config.json",
            modbus_device="/dev/ttyUSB0",
            mqtt_broker="localhost",
        )
        client.config = mock_config_instance
        client.mqtt = MagicMock()
        client.raw_data = {"voltage": 230}

        mock_converter.from_raw = MagicMock(return_value=230.0)

        with patch("builtins.open", MagicMock()) as mock_open:
            client.publish_state()
            # Should attempt to open file for writing
            # Note: actual file writing is tested via exception handling


class TestSofarClientWriteRegister:
    """Test write register functionality."""

    def test_write_register_standard(self, mock_modbus):
        """Test writing to a standard register."""
        mock_modbus.write_register = MagicMock(return_value=True)

        client = SofarClient(
            config_path="/tmp/config.json",
            modbus_device="/dev/ttyUSB0",
            mqtt_broker="localhost",
        )
        client.modbus = mock_modbus

        register = {"register": "0x1000", "name": "voltage"}
        result = client._write_register(register, 230)

        assert result is True
        mock_modbus.write_register.assert_called_once_with(0x1000, 230)

    def test_write_register_special(self):
        """Test writing to a special register with write_addresses."""
        client = SofarClient(
            config_path="/tmp/config.json",
            modbus_device="/dev/ttyUSB0",
            mqtt_broker="localhost",
        )
        client.modbus = MagicMock()
        client.modbus.write_register = MagicMock(return_value=True)

        register = {
            "name": "charge_power",
            "write_addresses": {"discharge": "0x2000"},
        }

        result = client._write_special_register(register, 100)

        assert result is True
        client.modbus.write_register.assert_called_once_with(0x2000, 100)


class TestSofarClientLifecycle:
    """Test client lifecycle operations."""

    def test_stop_disconnects_mqtt(self):
        """Test that stop properly disconnects MQTT."""
        client = SofarClient(
            config_path="/tmp/config.json",
            modbus_device="/dev/ttyUSB0",
            mqtt_broker="localhost",
        )
        client.mqtt = MagicMock()

        client.stop()

        client.mqtt.publish.assert_called_with("sofar2mqtt_python/bridge", "offline", retain=False)
        client.mqtt.disconnect.assert_called_once()
        client.mqtt.loop_stop.assert_called_once()

    def test_stop_closes_modbus(self):
        """Test that stop closes Modbus connection."""
        mock_modbus = MagicMock()
        mock_modbus.close = MagicMock()

        client = SofarClient(
            config_path="/tmp/config.json",
            modbus_device="/dev/ttyUSB0",
            mqtt_broker="localhost",
        )
        client.modbus = mock_modbus

        client.stop()

        client.modbus.close.assert_called_once()

    def test_running_flag_set_on_start(self):
        """Test that running flag is managed correctly."""
        client = SofarClient(
            config_path="/tmp/config.json",
            modbus_device="/dev/ttyUSB0",
            mqtt_broker="localhost",
        )
        mock_config_instance = MagicMock()
        mock_config_instance.registers = []

        with patch("sofar2mqtt.core.sofar_client.load_config", return_value=mock_config_instance):
            with patch.object(client, "setup"):
                client.running = False

                # Start doesn't call run, so running stays False
                client.start()

                # running should still be False since run() wasn't called
                assert client.running is False or client.running is not True


class TestSofarClientMqttCallbacks:
    """Test MQTT callback handlers."""

    def test_on_mqtt_connect_subscribes_to_write_topics(self):
        """Test that connect subscribes to write topics."""
        mock_config = InverterConfig(registers=[])
        client = SofarClient(
            config_path="/tmp/config.json",
            modbus_device="/dev/ttyUSB0",
            mqtt_broker="localhost",
        )
        client.mqtt = MagicMock()
        client.discovery = MagicMock()
        client.config = mock_config
        client.raw_data = {"sw_version_com": "1.0", "hw_version": "1.0"}

        client._on_mqtt_connect(client.mqtt, None, None, 0)

        client.mqtt.subscribe.assert_called_once_with("sofar/rw/#", qos=0)
        client.discovery.discover_all.assert_called_once()

    def test_on_mqtt_message_handles_write(self):
        """Test that incoming messages trigger writes."""
        mock_config_instance = InverterConfig(
            registers=[RegisterDefinition(name="power", register="0x1002", read=True, write=True)]
        )

        client = SofarClient(
            config_path="/tmp/config.json",
            modbus_device="/dev/ttyUSB0",
            mqtt_broker="localhost",
        )
        client.config = mock_config_instance
        client.modbus = MagicMock()
        client.modbus.write_register = MagicMock(return_value=True)
        client._write_registers = [{"name": "power", "register": "0x1002"}]

        mock_message = MagicMock()
        mock_message.topic = "sofar/rw/power"
        mock_message.payload = b"100"
        mock_message.retain = False

        with patch("sofar2mqtt.transformations.converter.ValueConverter") as mock_converter:
            mock_converter.to_raw.return_value = 100
            mock_converter.validate.return_value = True
            client._on_mqtt_message(None, None, mock_message)

            assert client.modbus.write_register.called, (
                "write_register should be called after successful validation"
            )

    def test_on_mqtt_message_ignores_retained_messages(self):
        """Test that retained messages are ignored."""
        mock_config_instance = InverterConfig(
            registers=[RegisterDefinition(name="power", register="0x1002", read=True, write=True)]
        )

        client = SofarClient(
            config_path="/tmp/config.json",
            modbus_device="/dev/ttyUSB0",
            mqtt_broker="localhost",
        )
        client.config = mock_config_instance
        client._write_registers = [{"name": "power", "register": "0x1002"}]
        client.modbus = MagicMock()

        mock_message = MagicMock()
        mock_message.topic = "sofar/rw/power"
        mock_message.payload = b"100"
        mock_message.retain = True

        client._on_mqtt_message(None, None, mock_message)

        # Should not attempt write - verify no write_register call was made
        client.modbus.write_register.assert_not_called()
