# sofar2mqtt/transformations/ - Data Transformation Utilities

## Module Purpose

This module provides utilities for converting raw Modbus register values into human-readable formats and vice versa. It handles scaling, mode mapping, bit field extraction, and other transformations needed to interpret inverter data correctly.

## Key Components

### [`converter.py`](converter.py)
Main value conversion utilities:

**Class: `ValueConverter`**

Static utility class for bidirectional value conversion between raw Modbus format and normalized human-readable format.

### Conversion Methods

#### `from_raw(register: dict, raw_value: Any) -> Any`

Converts a raw Modbus value to its normalized human-readable form.

**Supported Transformations:**

| Function | Transformation | Example |
|----------|----------------|---------|
| `multiply` | `raw_value * factor` | `150 * 0.1 = 15.0` |
| `divide` | `raw_value / factor` | `150 / 10 = 15.0` |
| `mode` | Map numeric to string label | `1 -> "On"` |
| `bit_field` | Extract active bits as comma-separated list | `5 -> "Bit0,Bit2"` |
| `high_bit_low_bit` | Split 16-bit value into two bytes | `0x1234 -> "12-34"` |
| `history_event_map` | Format error code as event description | `42 -> "Event 42"` |
| `int` | Convert to integer | `"150" -> 150` |

**Example Usage:**

```python
register = {
    "name": "battery_voltage",
    "function": "divide",
    "factor": 10
}

raw_value = 235  # From Modbus
converted = ValueConverter.from_raw(register, raw_value)
# Result: 23.5
```

#### `to_raw(register: dict, value: Any) -> int`

Converts a human-readable value back to raw Modbus format for writing.

**Supported Reverse Transformations:**

| Function | Reverse Transformation | Example |
|----------|----------------------|---------|
| `multiply` | `int(value / factor)` | `15.0 / 0.1 = 150` |
| `divide` | `int(value * factor)` | `15.0 * 10 = 150` |
| `mode` | Look up string in modes dict | `"On" -> 1` |
| `bit_field` | Build bitmask from field names | `"Bit0,Bit2" -> 5` |
| `high_bit_low_bit` | Combine two bytes | `"12-34" -> 0x1234` |

**Example Usage:**

```python
register = {
    "name": "target_voltage",
    "function": "multiply",
    "factor": 0.1
}

human_value = 48.5
raw_value = ValueConverter.to_raw(register, human_value)
# Result: 485
```

#### `validate(register: dict, value: Any) -> bool`

Validates a value against register constraints (min, max, type).

**Validation Rules:**
- Value must not be None
- Value must be convertible to float
- Value must be within min/max bounds (if specified)
- Value must match expected type constraints

**Example Usage:**

```python
register = {
    "name": "temperature",
    "min": -20,
    "max": 80
}

is_valid = ValueConverter.validate(register, 25.5)
# Result: True

is_valid = ValueConverter.validate(register, 100)
# Result: False
```

### Helper Function: `combine_registers`

Combines multiple register values into a single value (for 32-bit values, strings, etc.).

**Usage:**

```python
# Combine two 16-bit registers into a 32-bit value
high = 0x1234
low = 0x5678
combined = combine_registers([high, low], "U32")
# Result: 0x12345678
```

## Transformation Details

### Multiply/Divide

Used for scaling raw integer values to physical units.

**Configuration:**
```json
{
  "name": "power",
  "function": "multiply",
  "factor": 0.1,
  "ha": {
    "unit_of_measurement": "W"
  }
}
```

**Examples:**
- Raw: `1500` → Converted: `150.0` (multiply by 0.1)
- Raw: `235` → Converted: `23.5` (divide by 10)

### Mode Mapping

Maps numeric values to human-readable string labels.

**Configuration:**
```json
{
  "name": "inverter_mode",
  "function": "mode",
  "modes": {
    "0": "Off",
    "1": "On",
    "2": "Auto",
    "3": "Backup"
  }
}
```

**Examples:**
- Raw: `2` → Converted: `"Auto"`
- Raw: `0` → Converted: `"Off"`

### Bit Field Extraction

Extracts individual bit flags from a value and returns them as a comma-separated list.

**Configuration:**
```json
{
  "name": "status_flags",
  "function": "bit_field",
  "fields": ["GridConnected", "Charging", "Discharging", "Fault"]
}
```

**Examples:**
- Raw: `5` (binary: 0101) → Converted: `"GridConnected,Discharging"`
- Raw: `3` (binary: 0011) → Converted: `"GridConnected,Charging"`

### High/Low Byte Splitting

Splits a 16-bit value into two separate bytes, often used for version numbers.

**Configuration:**
```json
{
  "name": "firmware_version",
  "function": "high_bit_low_bit",
  "join": "."
}
```

**Examples:**
- Raw: `0x0302` → Converted: `"3.2"`
- Raw: `0x1234` → Converted: `"18.52"`

### History Event Mapping

Maps error codes or event IDs to descriptive text.

**Configuration:**
```json
{
  "name": "last_event",
  "function": "history_event_map"
}
```

**Note:** This function currently returns the raw value as a string. Full implementation would require access to error code mappings from the configuration.

## Data Flow

```
┌─────────────┐     ┌─────────────────┐     ┌─────────────┐
│  Modbus     │────►│ ValueConverter  │────►│  MQTT       │
│  Raw Value  │     │ from_raw()      │     │  Publish    │
└─────────────┘     └─────────────────┘     └─────────────┘

┌─────────────┐     ┌─────────────────┐     ┌─────────────┐
│  MQTT       │────►│ ValueConverter  │────►│  Modbus     │
│  Command    │     │ to_raw()        │     │  Write      │
└─────────────┘     └─────────────────┘     └─────────────┘
```

## Error Handling

- **None Values**: Returns None without error
- **Invalid Function**: Returns raw value unchanged
- **Missing Fields**: Uses sensible defaults (factor=1, empty modes/fields)
- **Type Errors**: Logs warning, returns original value

## Usage in Application

### In sofar_client.py

```python
from sofar2mqtt.transformations.converter import ValueConverter

# Reading registers
for register in self.config.registers:
    raw_value = self.modbus.read_register(register.register)
    converted_value = ValueConverter.from_raw(
        register.model_dump(), raw_value
    )
    self.raw_data[register.name] = converted_value
```

### Handling Write Commands

```python
# From MQTT command
human_value = json.loads(payload)["value"]
raw_value = ValueConverter.to_raw(register_config, human_value)
self.modbus.write_register(register.address, raw_value)
```

## Testing Guidelines

```python
def test_multiply_conversion():
    register = {"function": "multiply", "factor": 0.1}
    assert ValueConverter.from_raw(register, 150) == 15.0
    assert ValueConverter.to_raw(register, 15.0) == 150

def test_mode_conversion():
    register = {
        "function": "mode",
        "modes": {"0": "Off", "1": "On"}
    }
    assert ValueConverter.from_raw(register, 1) == "On"
    assert ValueConverter.to_raw(register, "On") == 1

def test_bit_field_conversion():
    register = {
        "function": "bit_field",
        "fields": ["A", "B", "C"]
    }
    assert ValueConverter.from_raw(register, 5) == "A,C"
```

## Dependencies

- `typing`: Type hints (Any)
- `logging`: Error and warning logging

## Integration with Other Modules

| Module | Usage |
|--------|-------|
| `core/sofar_client.py` | Converts raw Modbus values before publishing |
| `mqtt/client.py` | Converts MQTT command values for writing |
| `config/loader.py` | Provides function/factor/modes configuration |
| `models/register.py` | Defines function types and constraints |
