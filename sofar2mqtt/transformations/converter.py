"""Value transformation utilities for Sofar2MQTT."""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ValueConverter:
    """Converts between raw Modbus register values and normalized human-readable values."""

    # Mapping of function names to handler method names
    _CONVERSION_FUNCTIONS: dict[str, str] = {
        "divide": "_divide",
        "multiply": "_multiply",
        "mode": "_mode",
        "bit_field": "_bit_field",
        "high_bit_low_bit": "_high_bit_low_bit",
        "bitmask": "_bitmask",
        "bitmask_map": "_bitmask_map",
        "bitmask_map_str": "_bitmask_map_str",
        "bitmask_map_str_or": "_bitmask_map_str_or",
        "history_event_map": "_format_history_event",
    }

    @staticmethod
    def from_raw(register: dict[str, Any], raw_value: Any) -> Any:
        """Convert a raw register value to its normalized form."""
        if raw_value is None:
            return None

        function = register.get("function")
        if not function:
            return raw_value

        handler_name = ValueConverter._CONVERSION_FUNCTIONS.get(function)
        if handler_name:
            handler = getattr(ValueConverter, handler_name)
            return handler(register, raw_value)

        logger.warning(f"Unknown conversion function: {function}")
        return raw_value

    @staticmethod
    def to_raw(register: dict[str, Any], value: Any) -> int:
        """Convert a human-readable value to raw Modbus format."""
        if value is None:
            return 0

        function = register.get("function")
        if not function:
            return int(value)

        # Reverse operations for to_raw
        if function == "divide":
            factor = register.get("factor", 1)
            return int(value * factor)
        elif function == "multiply":
            factor = register.get("factor", 1)
            return int(value / factor) if factor != 0 else int(value)
        elif function == "bitmask":
            return int(value)
        elif function in ("bitmask_map", "bitmask_map_str"):
            # Reverse lookup: find the key whose mapped value matches
            mapping = register.get("map") or register.get("mapping") or {}
            for k, v in mapping.items():
                if v == value:
                    return int(k)
            return int(value)
        elif function == "bitmask_map_str_or":
            return int(value)
        elif function == "history_event_map":
            return int(value)
        elif function == "mode":
            modes = register.get("modes") or {}
            for k, v in modes.items():
                if v == value:
                    return int(k)
            return int(value) if isinstance(value, (int, str)) else 0
        elif function == "bit_field":
            fields = register.get("fields", [])
            raw_value = 0
            if isinstance(value, str):
                selected_fields = [f.strip() for f in value.split(",")]
                for field in selected_fields:
                    if field in fields:
                        idx = len(fields) - 1 - fields.index(field)
                        raw_value |= 1 << idx
            return raw_value
        elif function == "high_bit_low_bit":
            join_char = register.get("join", "-")
            if isinstance(value, str):
                parts = value.split(join_char)
                if len(parts) == 2:
                    high = int(parts[0])
                    low = int(parts[1])
                    return (high << 8) | low
            return int(value)

        return int(value)

    @staticmethod
    def _divide(register: dict[str, Any], raw_value: int) -> float:
        """Divide raw value by factor."""
        factor = register.get("factor", 1)
        if factor == 0:
            logger.warning("Division by zero in divide function")
            return 0.0
        return raw_value / factor

    @staticmethod
    def _multiply(register: dict[str, Any], raw_value: int) -> float:
        """Multiply raw value by factor."""
        factor = register.get("factor", 1)
        return raw_value * factor

    @staticmethod
    def _bitmask(register: dict[str, Any], raw_value: int) -> int:
        """Apply bitmask to raw value."""
        mask = register.get("mask", 0xFFFF)
        return raw_value & mask

    @staticmethod
    def _bitmask_map(register: dict[str, Any], raw_value: int) -> Any:
        """Apply bitmask and map the masked result to a value."""
        mask = register.get("mask", 0xFFFF)
        mapping = register.get("map") or register.get("mapping") or {}
        masked = raw_value & mask
        return mapping.get(str(masked), mapping.get(masked, masked))

    @staticmethod
    def _bitmask_map_str(register: dict[str, Any], raw_value: int) -> str:
        """Apply bitmask and map the masked result to a string value."""
        return str(ValueConverter._bitmask_map(register, raw_value))

    @staticmethod
    def _bitmask_map_str_or(register: dict[str, Any], raw_value: int) -> str:
        """Apply bitmask and map to string value with OR logic."""
        mapping = register.get("map") or register.get("mapping") or {}
        result = []
        for bit in range(16):
            if raw_value & (1 << bit):
                key = str(1 << bit)
                if key in mapping:
                    result.append(mapping[key])
        return ", ".join(result) if result else str(raw_value)

    @staticmethod
    def _mode(register: dict[str, Any], raw_value: int) -> str:
        """Map raw numeric value to a descriptive mode string."""
        modes = register.get("modes") or {}
        return modes.get(str(raw_value), str(raw_value))

    @staticmethod
    def _bit_field(register: dict[str, Any], raw_value: int) -> str:
        """Convert bit flags to comma-separated field names."""
        fields = register.get("fields", [])
        result = []
        for i, field in enumerate(reversed(fields)):
            if raw_value & (1 << i):
                result.append(field)
        return ",".join(result)

    @staticmethod
    def _high_bit_low_bit(register: dict[str, Any], raw_value: int) -> str:
        """Split value into high and low bytes with join character."""
        high = raw_value >> 8
        low = raw_value & 0xFF
        join_char = register.get("join", "-")
        return f"{high:02}{join_char}{low:02}"

    @staticmethod
    def _format_history_event(register: dict[str, Any], raw_value: int) -> str:
        """Format a history event error code."""
        # Note: This would need access to error codes from config
        # For now, return the raw value as string
        return str(raw_value)

    @staticmethod
    def validate(register: dict[str, Any], value: Any) -> bool:
        """Validate value against register constraints."""
        if value is None:
            return False

        # Check range constraints
        min_val = register.get("min")
        max_val = register.get("max")

        if min_val is not None and value < min_val:
            return False
        if max_val is not None and value > max_val:
            return False

        # Check mode constraints
        function = register.get("function")
        if function == "mode":
            modes = register.get("modes", {})
            # Allow numeric values that map to modes
            if isinstance(value, (int, float)):
                if str(int(value)) not in modes:
                    return False
            # Allow string values that match mode descriptions
            elif isinstance(value, str):
                if value not in modes.values():
                    return False

        return True


def combine_registers(raw_data: dict[str, Any], register: dict[str, Any]) -> Any | None:
    """Combine multiple registers using the register's aggregate or combine method."""
    # Aggregate mode: combine values of other named registers (add/subtract/avg)
    agg_registers = register.get("aggregate")
    if agg_registers:
        agg_function = register.get("agg_function", "add")
        result = None

        for reg_name in agg_registers:
            if reg_name not in raw_data:
                logger.error(f"Aggregate register {reg_name} not found in data")
                return None

            value = raw_data[reg_name]
            if result is None:
                result = value
            elif agg_function == "add":
                result += value
            elif agg_function == "subtract":
                result -= value
            elif agg_function == "avg":
                result = int((result + value) / 2)
            else:
                logger.warning(f"Unknown aggregate function: {agg_function}")
                return None

        return result

    if not register.get("combine"):
        return None

    combine_method = register["combine"]
    register_addresses = register.get("registers", [])

    if combine_method == "concat":
        # Concatenate register values as strings
        values = [raw_data.get(addr) for addr in register_addresses]
        if None in values:
            return None
        return "".join(str(v) for v in values)

    elif combine_method == "float32":
        # Combine two 16-bit registers into a 32-bit float
        if len(register_addresses) < 2:
            return None
        high = raw_data.get(register_addresses[0])
        low = raw_data.get(register_addresses[1])
        if high is None or low is None:
            return None
        import struct

        return struct.unpack("f", struct.pack("HH", low, high))[0]

    elif combine_method == "uint32":
        # Combine two 16-bit registers into a 32-bit unsigned int
        if len(register_addresses) < 2:
            return None
        high = raw_data.get(register_addresses[0])
        low = raw_data.get(register_addresses[1])
        if high is None or low is None:
            return None
        return (high << 16) | low

    elif combine_method == "int32":
        # Combine two 16-bit registers into a 32-bit signed int
        if len(register_addresses) < 2:
            return None
        high = raw_data.get(register_addresses[0])
        low = raw_data.get(register_addresses[1])
        if high is None or low is None:
            return None
        value = (high << 16) | low
        if value >= 0x80000000:
            value -= 0x100000000
        return value

    logger.warning(f"Unknown combine method: {combine_method}")
    return None


def read_ascii(register: dict[str, Any], raw_value: Any) -> str:
    """Convert raw register value to ASCII string.

    Modbus registers are 16-bit, so each register can hold 2 ASCII characters.
    This function converts the raw integer value to its ASCII string representation.
    """
    if raw_value is None:
        return ""

    # Convert integer to bytes (big-endian, 2 bytes per register)
    if isinstance(raw_value, int):
        # Determine byte length - typically 2 bytes for a single register
        byte_length = 2
        try:
            return raw_value.to_bytes(byte_length, byteorder="big").decode("ascii").rstrip("\x00")
        except (UnicodeDecodeError, OverflowError):
            # If decoding fails, return the raw value as string
            return str(raw_value)
    elif isinstance(raw_value, bytes):
        return raw_value.decode("ascii").rstrip("\x00")
    elif isinstance(raw_value, str):
        return raw_value.rstrip("\x00")

    return str(raw_value)
