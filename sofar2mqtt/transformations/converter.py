"""Value transformation utilities for Sofar2MQTT."""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ValueConverter:
    """Converts between raw Modbus register values and normalized human-readable values."""

    @staticmethod
    def from_raw(register: dict[str, Any], raw_value: Any) -> Any:
        """Convert a raw register value to its normalized form."""
        if raw_value is None:
            return None

        function = register.get("function")

        if function == "multiply":
            return raw_value * register.get("factor", 1)
        elif function == "divide":
            return raw_value / register.get("factor", 1)
        elif function == "mode":
            modes = register.get("modes") or {}
            return modes.get(str(raw_value), raw_value)
        elif function == "bit_field":
            fields = register.get("fields", [])
            result = []
            for i, field in enumerate(reversed(fields)):
                if raw_value & (1 << i):
                    result.append(field)
            return ",".join(result)
        elif function == "high_bit_low_bit":
            high = raw_value >> 8
            low = raw_value & 0xFF
            join_char = register.get("join", "-")
            return f"{high:02}{join_char}{low:02}"
        elif function == "history_event_map":
            return ValueConverter._format_history_event(register, raw_value)
        elif function == "int":
            return int(raw_value)

        return raw_value

    @staticmethod
    def to_raw(register: dict[str, Any], value: Any) -> int:
        """Convert a human-readable value to raw Modbus format."""
        # Debug: Log the register and value
        logger.debug(f"to_raw called with register={register}, value={value}")
        if register is None:
            logger.error("register is None in to_raw!")
            return 0
        function = register.get("function")

        if function == "multiply":
            return int(float(value) / register.get("factor", 1))
        elif function == "divide":
            return int(float(value) * register.get("factor", 1))
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

        return int(value) if value is not None else 0

    @staticmethod
    def _format_history_event(register: dict[str, Any], raw_value: int) -> str:
        """Format a history event error code."""
        # Note: This would need access to error codes from config
        # For now, return the raw value as string
        return str(raw_value)

    @staticmethod
    def validate(register: dict[str, Any], value: Any) -> bool:
        """Validate a value against register constraints."""
        logger.debug(f"validate called with register={register}, value={value}")
        if register is None:
            logger.error("register is None in validate!")
            return False
        if value is None:
            return False

        try:
            float_value = float(value) if isinstance(value, (int, float, str)) else 0
        except (ValueError, TypeError):
            return False

        min_value = register.get("min")
        if min_value is not None and float_value < min_value:
            logger.error(f"Value {value} is less than min {min_value}")
            return False

        max_value = register.get("max")
        if max_value is not None and float_value > max_value:
            logger.error(f"Value {value} is greater than max {max_value}")
            return False

        if register.get("function") == "mode":
            modes = register.get("modes") or {}
            if str(value) not in modes and value not in modes.values():
                logger.error(f"Value {value} is not a valid mode")
                return False

        return True


def combine_registers(raw_data: dict[str, Any], register: dict[str, Any]) -> Any | None:
    """Combine multiple registers using aggregate function."""
    agg_registers = register.get("aggregate", [])
    if not agg_registers:
        return None

    agg_function = register.get("agg_function", "add")
    result = None

    for reg_name in agg_registers:
        if reg_name not in raw_data:
            logger.error(f"Aggregate register {reg_name} not found in data")
            return None

        value = raw_data[reg_name]

        if result is None:
            result = value
        else:
            if agg_function == "add":
                result += value
            elif agg_function == "subtract":
                result -= value
            elif agg_function == "avg":
                result = int((result + value) / 2)

    return result


def read_ascii(instrument, start_address: int, count: int) -> str | None:
    """Read ASCII string from consecutive registers."""
    try:
        regs = instrument.read_registers(start_address, count, functioncode=3)
    except Exception as e:
        logger.debug(f"Error reading registers at 0x{start_address:04X}: {e}")
        return None

    chars = []
    for val in regs:
        hi = (val >> 8) & 0xFF
        lo = val & 0xFF

        # Sofar stores ASCII in HIGH BYTE first
        for b in (hi, lo):
            if b == 0:
                continue
            c = chr(b)
            if c.isprintable():
                chars.append(c)

    return "".join(chars)
