"""Tests for value conversion and transformation logic."""

from sofar2mqtt.transformations.converter import ValueConverter, combine_registers


class TestValueConverterFromRaw:
    """Tests for ValueConverter.from_raw() method."""

    def test_no_function_returns_raw_value(self):
        """Test that registers without a function return the raw value."""
        register = {"address": 100}
        assert ValueConverter.from_raw(register, 42) == 42

    def test_divide_function(self):
        """Test division conversion."""
        register = {"function": "divide", "factor": 10}
        assert ValueConverter.from_raw(register, 123) == 12.3

    def test_multiply_function(self):
        """Test multiplication conversion."""
        register = {"function": "multiply", "factor": 10}
        assert ValueConverter.from_raw(register, 12.3) == 123

    def test_bitmask_function(self):
        """Test bitmask conversion."""
        register = {"function": "bitmask", "mask": 0x0F}
        assert ValueConverter.from_raw(register, 0xFF) == 0x0F

    def test_bitmask_map_function(self):
        """Test bitmask mapping conversion."""
        register = {
            "function": "bitmask_map",
            "mask": 0x03,
            "map": {"0": "off", "1": "on", "2": "auto"},
        }
        # 0x02 & 0x03 = 2 -> "auto"
        assert ValueConverter.from_raw(register, 0x02) == "auto"

    def test_bitmask_map_str_function(self):
        """Test bitmask mapping with string values."""
        register = {
            "function": "bitmask_map_str",
            "mask": 0x03,
            "map": {"0": "off", "1": "on", "2": "auto"},
        }
        assert ValueConverter.from_raw(register, 0x02) == "auto"

    def test_history_event_map_function(self):
        """Test history event mapping conversion."""
        register = {"function": "history_event_map"}
        assert ValueConverter.from_raw(register, 123) == "123"

    def test_none_value_returns_none(self):
        """Test that None values are handled correctly."""
        register = {"function": "divide", "factor": 10}
        assert ValueConverter.from_raw(register, None) is None

    def test_unknown_function_returns_raw_value(self):
        """Test that unknown functions return the raw value."""
        register = {"function": "unknown_function"}
        assert ValueConverter.from_raw(register, 42) == 42


class TestValueConverterToRaw:
    """Tests for ValueConverter.to_raw() method."""

    def test_no_function_returns_int(self):
        """Test that registers without a function return int value."""
        register = {"address": 100}
        assert ValueConverter.to_raw(register, 42) == 42

    def test_divide_function_reverse(self):
        """Test reverse division conversion."""
        register = {"function": "divide", "factor": 10}
        assert ValueConverter.to_raw(register, 12.3) == 123

    def test_multiply_function_reverse(self):
        """Test reverse multiplication conversion (inverse of from_raw: value / factor)."""
        register = {"function": "multiply", "factor": 10}
        assert ValueConverter.to_raw(register, 123) == 12

    def test_none_value_returns_zero(self):
        """Test that None values return 0."""
        register = {"function": "divide", "factor": 10}
        assert ValueConverter.to_raw(register, None) == 0

    def test_bitmask_map_function_reverse(self):
        """Test reverse bitmask mapping conversion."""
        register = {
            "function": "bitmask_map",
            "mask": 0x03,
            "map": {"0": "off", "1": "on", "2": "auto"},
        }
        assert ValueConverter.to_raw(register, "auto") == 2


class TestCombineRegisters:
    """Tests for combine_registers() function."""

    def test_concat_method(self):
        """Test concatenation of register values."""
        register = {"combine": "concat", "registers": ["addr1", "addr2"]}
        raw_data = {"addr1": "123", "addr2": "456"}
        assert combine_registers(raw_data, register) == "123456"

    def test_concat_with_none(self):
        """Test concatenation with missing values."""
        register = {"combine": "concat", "registers": ["addr1", "addr2"]}
        raw_data = {"addr1": "123"}
        assert combine_registers(raw_data, register) is None

    def test_float32_method(self):
        """Test float32 combination."""
        register = {"combine": "float32", "registers": ["high", "low"]}
        raw_data = {"high": 0x4049, "low": 0x0FDB}  # Approx pi
        result = combine_registers(raw_data, register)
        assert isinstance(result, float)
        assert abs(result - 3.14159) < 0.001

    def test_uint32_method(self):
        """Test uint32 combination."""
        register = {"combine": "uint32", "registers": ["high", "low"]}
        raw_data = {"high": 0x0001, "low": 0x0002}
        assert combine_registers(raw_data, register) == 0x00010002

    def test_int32_method(self):
        """Test int32 combination."""
        register = {"combine": "int32", "registers": ["high", "low"]}
        raw_data = {"high": 0xFFFF, "low": 0xFFFF}  # -1 in two's complement
        assert combine_registers(raw_data, register) == -1

    def test_unknown_combine_method(self):
        """Test unknown combine method returns None."""
        register = {"combine": "unknown_method", "registers": ["addr1"]}
        raw_data = {"addr1": 123}
        assert combine_registers(raw_data, register) is None

    def test_no_combine_method(self):
        """Test register without combine method returns None."""
        register = {"address": 100}
        raw_data = {"address": 123}
        assert combine_registers(raw_data, register) is None


class TestCombineRegistersAggregate:
    """Tests for combine_registers() aggregate mode (named registers)."""

    def test_aggregate_add(self):
        """Test adding aggregated registers."""
        register = {"aggregate": ["power_a", "power_b"], "agg_function": "add"}
        raw_data = {"power_a": 100, "power_b": 200}
        assert combine_registers(raw_data, register) == 300

    def test_aggregate_avg(self):
        """Test averaging aggregated registers."""
        register = {"aggregate": ["power_a", "power_b"], "agg_function": "avg"}
        raw_data = {"power_a": 100, "power_b": 200}
        assert combine_registers(raw_data, register) == 150

    def test_aggregate_subtract(self):
        """Test subtracting aggregated registers."""
        register = {"aggregate": ["power_a", "power_b"], "agg_function": "subtract"}
        raw_data = {"power_a": 300, "power_b": 100}
        assert combine_registers(raw_data, register) == 200

    def test_aggregate_missing_data(self):
        """Test missing aggregate values return None."""
        register = {"aggregate": ["power_a", "power_b"], "agg_function": "add"}
        raw_data = {"power_a": 100}
        assert combine_registers(raw_data, register) is None

    def test_aggregate_unknown_function(self):
        """Test unknown aggregate function returns None."""
        register = {"aggregate": ["power_a", "power_b"], "agg_function": "max"}
        raw_data = {"power_a": 100, "power_b": 200}
        assert combine_registers(raw_data, register) is None
