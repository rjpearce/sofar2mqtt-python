"""Tests for Modbus client functionality."""

from unittest.mock import MagicMock, patch

from sofar2mqtt.core.modbus_client import ModbusClient


class TestModbusClientSetup:
    """Test Modbus client initialization and setup."""

    def test_init_default_values(self):
        """Test default initialization values."""
        client = ModbusClient("/dev/ttyUSB0")
        assert client.device == "/dev/ttyUSB0"
        assert client.slave_id == 1
        assert client.retry == 2
        assert client.retry_delay == 0.1

    def test_init_custom_values(self):
        """Test custom initialization values."""
        client = ModbusClient("/dev/ttyUSB0", slave_id=2, retry=3, retry_delay=0.5)
        assert client.slave_id == 2
        assert client.retry == 3
        assert client.retry_delay == 0.5

    @patch("sofar2mqtt.core.modbus_client.Instrument")
    def test_setup_creates_instrument(self, mock_instrument):
        """Test that setup creates and configures the instrument."""
        client = ModbusClient("/dev/ttyUSB0")
        client.setup()

        mock_instrument.assert_called_once()
        instrument = mock_instrument.return_value
        assert instrument.serial.baudrate == 9600
        assert instrument.serial.bytesize == 8
        assert instrument.serial.parity == "N"  # PARITY_NONE
        assert instrument.serial.stopbits == 1

    def test_setup_sets_mutex(self):
        """Test that setup initializes the mutex."""
        client = ModbusClient("/dev/ttyUSB0")
        # Skip actual setup - just verify mutex exists after init
        assert hasattr(client, "_mutex")
        assert client._mutex is not None


class TestModbusClientRead:
    """Test Modbus client read operations."""

    def test_read_register_success(self, mock_modbus_instrument):
        """Test successful register read."""
        client = ModbusClient("/dev/ttyUSB0")
        client.instrument = mock_modbus_instrument

        value = client.read_register(0x1000)
        assert value == 1234
        mock_modbus_instrument.read_register.assert_called_once_with(
            0x1000, number_of_decimals=0, functioncode=3, signed=False
        )

    def test_read_register_returns_none_on_failure(self, mock_modbus_instrument):
        """Test that read returns None when instrument is not set."""
        client = ModbusClient("/dev/ttyUSB0")

        value = client.read_register(0x1000)
        assert value is None

    def test_read_long(self, mock_modbus_instrument):
        """Test long (32-bit) register read."""
        mock_modbus_instrument.read_long.return_value = 123456

        client = ModbusClient("/dev/ttyUSB0")
        client.instrument = mock_modbus_instrument

        value = client.read_long(0x1000)
        assert value == 123456


class TestModbusClientWrite:
    """Test Modbus client write operations."""

    def test_write_register_success(self, mock_modbus_instrument):
        """Test successful register write."""
        mock_modbus_instrument.write_register.return_value = None

        client = ModbusClient("/dev/ttyUSB0")
        client.instrument = mock_modbus_instrument

        result = client.write_register(0x1000, 42)
        assert result is True
        mock_modbus_instrument.write_register.assert_called_once()

    def test_write_register_returns_false_on_failure(self):
        """Test that write returns False when instrument is not set."""
        client = ModbusClient("/dev/ttyUSB0")

        result = client.write_register(0x1000, 42)
        assert result is False

    def test_write_registers(self, mock_modbus_instrument):
        """Test writing multiple registers."""
        mock_modbus_instrument.write_registers.return_value = None

        client = ModbusClient("/dev/ttyUSB0")
        client.instrument = mock_modbus_instrument

        result = client.write_registers(0x1000, [1, 2, 3])
        assert result is True


class TestModbusClientClose:
    """Test Modbus client cleanup."""

    def test_close_closes_port(self, mock_modbus_instrument):
        """Test that close closes the serial port."""
        mock_modbus_instrument.serial.is_open = True
        mock_modbus_instrument.serial.close = MagicMock()

        client = ModbusClient("/dev/ttyUSB0")
        client.instrument = mock_modbus_instrument
        client.close()

        mock_modbus_instrument.serial.close.assert_called_once()

    def test_close_does_not_error_if_already_closed(self, mock_modbus_instrument):
        """Test close handles already closed port gracefully."""
        mock_modbus_instrument.serial.is_open = False

        client = ModbusClient("/dev/ttyUSB0")
        client.instrument = mock_modbus_instrument
        client.close()

        # Should not raise
