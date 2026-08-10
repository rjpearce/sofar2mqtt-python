"""Tests for Modbus client functionality."""

from unittest.mock import MagicMock, patch

import pytest
from minimalmodbus import NoResponseError

from sofar2mqtt.core.modbus_client import ModbusClient


class TestModbusClient:
    """Tests for ModbusClient class."""

    @pytest.fixture
    def client(self):
        """Create a ModbusClient instance."""
        return ModbusClient("/dev/ttyUSB0", 1, retry=3, retry_delay=0.1)

    def test_initialization(self, client):
        """Test client initialization."""
        assert client.device == "/dev/ttyUSB0"
        assert client.slave_id == 1
        assert client.retry == 3
        assert client.retry_delay == 0.1
        assert client.instrument is None

    def test_setup_creates_instrument(self, client):
        """Test that setup creates and configures the instrument."""
        with patch("sofar2mqtt.core.modbus_client.Instrument") as MockInstrument:
            mock_instrument = MagicMock()
            MockInstrument.return_value = mock_instrument

            client.setup()

            MockInstrument.assert_called_once_with("/dev/ttyUSB0", 1)
            assert client.instrument == mock_instrument
            assert mock_instrument.close_port_after_each_call is True

    def test_check_initialized_false(self, client):
        """Test _check_initialized returns False when not initialized."""
        assert client._check_initialized() is False

    def test_check_initialized_true(self, client):
        """Test _check_initialized returns True when initialized."""
        client.instrument = MagicMock()
        assert client._check_initialized() is True

    def test_execute_with_retry_success(self, client):
        """Test _execute_with_retry on success."""
        mock_operation = MagicMock(return_value=42)
        result = client._execute_with_retry(mock_operation, "Test error")
        assert result == 42
        mock_operation.assert_called_once()

    def test_execute_with_retry_failure(self, client):
        """Test _execute_with_retry on failure."""
        mock_operation = MagicMock(side_effect=NoResponseError("Test error"))
        result = client._execute_with_retry(mock_operation, "Test error", default=-1)
        assert result == -1
        assert mock_operation.call_count == 3  # retry=3

    def test_read_register_success(self, client):
        """Test read_register on success."""
        client.instrument = MagicMock()
        client.instrument.read_register.return_value = 1234

        result = client.read_register(100)
        assert result == 1234
        client.instrument.read_register.assert_called_once_with(100, functioncode=3, signed=True)

    def test_read_register_not_initialized(self, client):
        """Test read_register returns None when not initialized."""
        result = client.read_register(100)
        assert result is None

    def test_read_long_success(self, client):
        """Test read_long on success."""
        client.instrument = MagicMock()
        client.instrument.read_long.return_value = 123456789

        result = client.read_long(100)
        assert result == 123456789
        client.instrument.read_long.assert_called_once_with(100, signed=True)

    def test_read_string_success(self, client):
        """Test read_string on success."""
        client.instrument = MagicMock()
        client.instrument.read_string.return_value = "test"

        result = client.read_string(100, count=8)
        assert result == "test"
        client.instrument.read_string.assert_called_once_with(100, 8)

    def test_write_register_success(self, client):
        """Test write_register on success."""
        client.instrument = MagicMock()

        result = client.write_register(100, 42)
        assert result is True
        client.instrument.write_register.assert_called_once_with(100, 42)

    def test_write_registers_success(self, client):
        """Test write_registers on success."""
        client.instrument = MagicMock()

        result = client.write_registers(100, [1, 2, 3])
        assert result is True
        client.instrument.write_registers.assert_called_once_with(100, [1, 2, 3])

    def test_write_register_special_success(self, client):
        """Test write_register_special on success."""
        client.instrument = MagicMock()
        client.instrument._perform_command.return_value = b"\x01\x02\x03"

        result = client.write_register_special(100, 16, 42)
        assert result == b"\x01\x02\x03"
        client.instrument._perform_command.assert_called_once()

    def test_read_ascii_success(self, client):
        """Test read_ascii on success."""
        client.instrument = MagicMock()
        client.instrument.read_registers.return_value = [0x4142, 0x4344]  # "ABCD"

        result = client.read_ascii(100, 2)
        assert result == "ABCD"
        client.instrument.read_registers.assert_called_once_with(100, 2, functioncode=3)

    def test_close_closes_connection(self, client):
        """Test close() closes the serial connection."""
        client.instrument = MagicMock()
        client.instrument.serial.is_open = True

        client.close()
        client.instrument.serial.close.assert_called_once()

    def test_close_when_not_open(self, client):
        """Test close() when connection is not open."""
        client.instrument = MagicMock()
        client.instrument.serial.is_open = False

        client.close()
        client.instrument.serial.close.assert_not_called()
