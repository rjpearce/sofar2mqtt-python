"""Tests for value conversion and transformation logic."""

from sofar2mqtt.transformations.converter import ValueConverter, combine_registers


class TestValueConverterFromRaw:
    """Test conversion from raw values to normalized values."""

    def test_from_raw_no_function_returns_raw(self):
        """Test that values without function are returned as-is."""
        register = {"name": "voltage"}
        result = ValueConverter.from_raw(register, 230.5)
        assert result == 230.5

    def test_from_raw_with_multiply_function(self):
        """Test multiply function applies factor."""
        register = {
            "name": "power",
            "function": "multiply",
            "factor": 0.1,
        }
        result = ValueConverter.from_raw(register, 123)
        assert result == 12.3

    def test_from_raw_with_divide_function(self):
        """Test divide function applies factor."""
        register = {
            "name": "current",
            "function": "divide",
            "factor": 100,
        }
        result = ValueConverter.from_raw(register, 1234)
        assert result == 12.34

    def test_from_raw_with_mode_function(self):
        """Test mode function applies string mapping."""
        register = {
            "name": "energy_mode",
            "function": "mode",
            "modes": {"0": "passive", "1": "self_use", "2": "backup"},
        }
        result = ValueConverter.from_raw(register, 1)
        assert result == "self_use"

    def test_from_raw_with_bit_field_function(self):
        """Test bit field function converts bits to list."""
        register = {
            "name": "alarm_status",
            "function": "bit_field",
            "fields": ["alarm1", "alarm2", "alarm3"],
        }
        # Binary 101 = alarm1 and alarm3 set
        result = ValueConverter.from_raw(register, 5)
        assert "alarm1" in result
        assert "alarm3" in result
        assert "alarm2" not in result

    def test_from_raw_with_high_bit_low_bit(self):
        """Test high bit/low bit formatting."""
        register = {
            "name": "serial_number",
            "function": "high_bit_low_bit",
            "join": "-",
        }
        # 0x1234: high=0x12=18, low=0x34=52
        result = ValueConverter.from_raw(register, 0x1234)
        assert result == "18-52"

    def test_from_raw_with_int_function(self):
        """Test int function converts string to int."""
        register = {
            "name": "version_numeric",
            "function": "int",
        }
        result = ValueConverter.from_raw(register, "12345")
        assert result == 12345

    def test_from_raw_with_none_value(self):
        """Test None values are handled gracefully."""
        register = {"name": "unknown"}
        result = ValueConverter.from_raw(register, None)
        assert result is None


class TestValueConverterToRaw:
    """Test conversion from normalized to raw values."""

    def test_to_raw_no_function_returns_int(self):
        """Test values without function are converted to int."""
        register = {"name": "voltage"}
        result = ValueConverter.to_raw(register, 230.5)
        assert result == 230

    def test_to_raw_with_multiply_function(self):
        """Test multiply function reverses division."""
        register = {
            "name": "power",
            "function": "multiply",
            "factor": 0.1,
        }
        result = ValueConverter.to_raw(register, 12.3)
        assert result == 123

    def test_to_raw_with_divide_function(self):
        """Test divide function reverses multiplication."""
        register = {
            "name": "current",
            "function": "divide",
            "factor": 100,
        }
        result = ValueConverter.to_raw(register, 12.34)
        assert result == 1234

    def test_to_raw_with_mode_function(self):
        """Test mode function inverts string mapping."""
        register = {
            "name": "energy_mode",
            "function": "mode",
            "modes": {"0": "passive", "1": "self_use", "2": "backup"},
        }
        result = ValueConverter.to_raw(register, "self_use")
        assert result == 1

    def test_to_raw_with_bit_field_function(self):
        """Test bit field creates bitmask from selection."""
        register = {
            "name": "alarm_status",
            "function": "bit_field",
            "fields": ["alarm1", "alarm2", "alarm3"],
        }
        result = ValueConverter.to_raw(register, "alarm1,alarm3")
        assert result == 5  # Binary 101

    def test_to_raw_with_high_bit_low_bit(self):
        """Test high bit/low bit parsing."""
        register = {
            "name": "serial_number",
            "function": "high_bit_low_bit",
            "join": "-",
        }
        # "18-52" should convert to 0x1234 (18*256 + 52 = 4660 = 0x1234)
        result = ValueConverter.to_raw(register, "18-52")
        assert result == 0x1234

    def test_to_raw_with_none_value(self):
        """Test None values default to 0."""
        register = {"name": "unknown"}
        result = ValueConverter.to_raw(register, None)
        assert result == 0


class TestValueConverterValidate:
    """Test value validation."""

    def test_validate_with_range(self):
        """Test validation against min/max bounds."""
        register = {
            "name": "voltage",
            "min": 0,
            "max": 500,
        }
        assert ValueConverter.validate(register, 100) is True
        assert ValueConverter.validate(register, 0) is True
        assert ValueConverter.validate(register, 500) is True
        assert ValueConverter.validate(register, -1) is False
        assert ValueConverter.validate(register, 501) is False

    def test_validate_with_mode_function(self):
        """Test validation against mode options."""
        register = {
            "name": "energy_mode",
            "function": "mode",
            "modes": {"0": "passive", "1": "self_use", "2": "backup"},
        }
        # "self_use" is a valid MODE value
        assert ValueConverter.validate(register, 1) is True
        assert ValueConverter.validate(register, 2) is True
        assert ValueConverter.validate(register, "invalid") is False

    def test_validate_with_none_value(self):
        """Test None values are invalid."""
        register = {"name": "voltage"}
        assert ValueConverter.validate(register, None) is False

    def test_validate_with_invalid_type(self):
        """Test invalid types are handled gracefully."""
        register = {"name": "voltage"}
        # This should not raise an exception
        result = ValueConverter.validate(register, "123")
        assert result is True


class TestCombineRegisters:
    """Test aggregate register combination."""

    def test_combine_registers_add(self):
        """Test adding combined registers."""
        raw_data = {"power_a": 100, "power_b": 200}
        register = {
            "aggregate": ["power_a", "power_b"],
            "agg_function": "add",
        }
        result = combine_registers(raw_data, register)
        assert result == 300

    def test_combine_registers_avg(self):
        """Test averaging combined registers."""
        raw_data = {"power_a": 100, "power_b": 200}
        register = {
            "aggregate": ["power_a", "power_b"],
            "agg_function": "avg",
        }
        result = combine_registers(raw_data, register)
        assert result == 150

    def test_combine_registers_subtract(self):
        """Test subtracting combined registers."""
        raw_data = {"power_a": 300, "power_b": 100}
        register = {
            "aggregate": ["power_a", "power_b"],
            "agg_function": "subtract",
        }
        result = combine_registers(raw_data, register)
        assert result == 200

    def test_combine_registers_missing_data(self):
        """Test missing aggregate values return None."""
        raw_data = {"power_a": 100}
        register = {
            "aggregate": ["power_a", "power_b"],
            "agg_function": "add",
        }
        result = combine_registers(raw_data, register)
        assert result is None

    def test_combine_registers_no_aggregate(self):
        """Test register without aggregate returns None."""
        raw_data = {"power": 100}
        register = {}
        result = combine_registers(raw_data, register)
        assert result is None
