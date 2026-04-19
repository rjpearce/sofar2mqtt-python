# sofar2mqtt/config/ - Configuration Management

## Module Purpose

This module handles loading, parsing, and validation of inverter configuration files. Configuration is stored as JSON files that define register mappings, transformation rules, and Home Assistant discovery metadata for different Sofar inverter models.

## Key Components

### [`loader.py`](loader.py)
Configuration loading and validation logic:

**Responsibilities:**
- Load JSON configuration files from disk
- Validate required fields and data structures
- Map raw JSON to Pydantic models (`InverterConfig`, `RegisterDefinition`)
- Log warnings for deprecated or problematic configurations

**Key Functions:**
- `load_config(config_path: str) -> InverterConfig`: Main entry point for loading configs
- `validate_registers(registers: list) -> None`: Check register definitions for issues

**Validation Rules:**
- `registers` key must be present in config
- Each register must have a unique `name`
- Register addresses should be valid hex strings (e.g., `"0x1234"`)
- Transformation functions must match supported types

## Configuration File Structure

Configuration files are stored in the `config/` directory at repository root:

```json
{
  "registers": [
    {
      "name": "register_name",
      "register": "0x1234",           // Modbus address (hex)
      "read_type": "register",         // register, long, string, static
      "type": "U16",                   // U16, I16, U32, I32
      "function": "multiply",          // multiply, divide, mode, bit_field, etc.
      "factor": 0.1,                   // Scaling factor for multiply/divide
      "modes": {"0": "Off", "1": "On"},// Mode mapping for mode function
      "fields": ["field1", "field2"],  // Bit field names for bit_field function
      "write": false,                  // Is this register writable?
      "refresh": 10,                   // Poll every N iterations
      "ha": {                          // Home Assistant discovery config
        "name": "Display Name",
        "device_class": "power",
        "unit_of_measurement": "W"
      }
    }
  ],
  "write_register_blocks": [...],     // Multi-register write blocks
  "error_codes": {...}                // Error code mappings
}
```

## Supported Read Types

| Type | Description | Registers Used |
|------|-------------|----------------|
| `register` | Single 16-bit register | 1 |
| `long` | 32-bit value (two registers) | 2 |
| `string` | ASCII string from multiple registers | Variable |
| `static` | Static value (not read from inverter) | 0 |

## Supported Data Types

| Type | Description | Range |
|------|-------------|-------|
| `U16` | Unsigned 16-bit integer | 0 - 65535 |
| `I16` | Signed 16-bit integer | -32768 - 32767 |
| `U32` | Unsigned 32-bit integer | 0 - 4,294,967,295 |
| `I32` | Signed 32-bit integer | -2,147,483,648 - 2,147,483,647 |

## Supported Transformation Functions

| Function | Description | Required Fields |
|----------|-------------|-----------------|
| `multiply` | Multiply raw value by factor | `factor` |
| `divide` | Divide raw value by factor | `factor` |
| `mode` | Map numeric value to string label | `modes` (dict) |
| `bit_field` | Extract bit flags as comma-separated list | `fields` (list) |
| `high_bit_low_bit` | Split 16-bit value into two bytes | `join` (optional) |
| `int` | Convert to integer | - |
| `history_event_map` | Map error codes to descriptions | - |

## Extending Configuration

### Adding a New Inverter Model

1. Create new JSON file in `config/` directory (e.g., `SOFAR-NEW-MODEL.json`)
2. Define all registers with addresses, types, and transformations
3. Add Home Assistant discovery metadata for each register
4. Test with `--config` CLI option

### Adding a New Transformation Function

1. Implement function in `sofar2mqtt/transformations/converter.py`
2. Add to `ValueConverter.from_raw()` and `to_raw()` methods
3. Update type hints in `RegisterDefinition.function` field

## Error Handling

- **File Not Found**: Raises `FileNotFoundError` with clear path
- **Invalid JSON**: Raises `json.JSONDecodeError` with line number
- **Missing Fields**: Raises `ValueError` with missing field name
- **Duplicate Registers**: Logs warning, allows duplicate (last wins)

## Testing Guidelines

- Test with valid and invalid JSON files
- Verify validation catches missing required fields
- Test edge cases (empty registers, null values)
- Mock file system for unit tests

## Dependencies

- `pydantic`: Data validation and model serialization
- `json`: Standard library JSON parsing
