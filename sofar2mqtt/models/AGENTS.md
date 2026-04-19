# sofar2mqtt/models/ - Pydantic Data Models

## Module Purpose

This module defines Pydantic data models used throughout the application for configuration validation, data serialization, and type safety. These models provide a structured way to represent inverter configurations, register definitions, and Home Assistant discovery payloads.

## Key Components

### [`inverter_config.py`](inverter_config.py)
Main inverter configuration model:

**Class: `InverterConfig`**

The root model representing a complete inverter configuration loaded from JSON.

**Attributes:**
- `registers: list[RegisterDefinition]`: List of all register definitions
- `write_register_blocks: list[WriteRegisterBlock] | None`: Multi-register write blocks
- `error_codes: dict[str, Any] | None`: Error code mappings

**Methods:**
- `from_dict(data: dict) -> InverterConfig`: Class method to create instance from dictionary

**Configuration:**
- `extra = "allow"`: Allows additional fields not defined in the model

### [`register.py`](register.py)
Register and Home Assistant configuration models:

**Class: `HomeAssistantConfig`**

Model for Home Assistant MQTT auto-discovery payload configuration.

**Key Attributes:**
| Attribute | Type | Description |
|-----------|------|-------------|
| `name` | str \| None | Display name for the entity |
| `object_id` | str \| None | Entity object ID |
| `unique_id` | str \| None | Unique identifier for the entity |
| `device_class` | str \| None | Home Assistant device class |
| `entity_category` | str \| None | Entity category (diagnostic, config) |
| `state_class` | str \| None | State class (measurement, total) |
| `unit_of_measurement` | str \| None | Unit of measurement |
| `icon` | str \| None | Material design icon |
| `control` | Literal["number", "select", "text"] \| None | Control type for writable entities |
| `min` / `max` | float \| None | Value constraints |
| `step` | float \| None | Increment step for number controls |
| `mode` | Literal["slider", "box"] \| None | Input mode for number controls |
| `enabled_by_default` | bool | Whether entity is enabled by default |
| `options` | list[str] \| None | Options for select controls |

**Class: `RegisterDefinition`**

Model representing a single Modbus register definition.

**Core Attributes:**
| Attribute | Type | Description |
|-----------|------|-------------|
| `name` | str | Unique register name |
| `register` | str \| None | Modbus address in hex (e.g., "0x1234") |
| `read_type` | Literal | How to read: "register", "long", "string", "static" |
| `type` | Literal | Data type: "U16", "I16", "U32", "I32" |
| `function` | Literal | Transformation: "multiply", "divide", "mode", etc. |
| `factor` | float \| None | Scaling factor for multiply/divide |
| `modes` | dict[str, str] \| None | Mode mapping for mode function |
| `fields` | list[str] \| None | Bit field names for bit_field function |
| `write` | bool | Whether register is writable |
| `read` | bool | Whether register is readable |
| `refresh` | int | Poll frequency (every N iterations) |
| `notify_on_change` | bool | Publish only when value changes |
| `ha` | HomeAssistantConfig \| None | Home Assistant discovery config |
| `value` | Any \| None | Static value for static read_type |

**Advanced Attributes:**
- `aggregate`: List of register names to combine
- `agg_function`: Aggregation function ("add", "subtract", "avg")
- `aggregate_datetime_bitmap`: Datetime bitmap configuration
- `write_addresses`: Write address mappings
- `passive`: Don't poll this register
- `untested`: Track untested registers

**Class: `WriteRegisterBlock`**

Model for grouping multiple registers into a single write operation.

**Attributes:**
- `name`: Block name
- `start_register`: Starting hex address
- `length`: Number of registers in block
- `registers`: List of register names
- `append`: Values to append at the end

## Read Types Explained

| Read Type | Description | Registers Used | Example |
|-----------|-------------|----------------|---------|
| `register` | Single 16-bit register | 1 | Temperature reading |
| `long` | 32-bit value (two registers) | 2 | Energy total |
| `string` | ASCII string from registers | Variable | Firmware version |
| `static` | Static value (not read) | 0 | Device model name |

## Data Types Explained

| Type | Size | Signed | Range |
|------|------|--------|-------|
| `U16` | 16-bit | No | 0 - 65,535 |
| `I16` | 16-bit | Yes | -32,768 - 32,767 |
| `U32` | 32-bit | No | 0 - 4,294,967,295 |
| `I32` | 32-bit | Yes | -2,147,483,648 - 2,147,483,647 |

## Transformation Functions

| Function | Purpose | Required Fields |
|----------|---------|-----------------|
| `multiply` | Scale value up | `factor` |
| `divide` | Scale value down | `factor` |
| `mode` | Map numeric to string | `modes` dict |
| `bit_field` | Extract bit flags | `fields` list |
| `high_bit_low_bit` | Split 16-bit value | `join` char |
| `int` | Convert to integer | - |
| `history_event_map` | Map error codes | - |

## Usage Examples

### Creating a Configuration

```python
from sofar2mqtt.models.inverter_config import InverterConfig
from sofar2mqtt.models.register import RegisterDefinition, HomeAssistantConfig

# Create a register definition
register = RegisterDefinition(
    name="battery_voltage",
    register="0x1000",
    read_type="register",
    type="U16",
    function="divide",
    factor=10,
    ha=HomeAssistantConfig(
        name="Battery Voltage",
        device_class="voltage",
        unit_of_measurement="V",
        state_class="measurement"
    )
)

# Create configuration
config = InverterConfig(registers=[register])
```

### Loading from Dictionary

```python
data = {
    "registers": [
        {
            "name": "inverter_mode",
            "register": "0x2000",
            "read_type": "register",
            "type": "U16",
            "function": "mode",
            "modes": {"0": "Off", "1": "On", "2": "Auto"},
            "ha": {
                "name": "Mode",
                "control": "select",
                "options": ["Off", "On", "Auto"]
            }
        }
    ]
}

config = InverterConfig.from_dict(data)
```

## Serialization

All models support Pydantic's built-in serialization:

```python
# To dictionary
data_dict = config.model_dump()

# To JSON string
json_str = config.model_dump_json()

# With exclusions
data_dict = config.model_dump(exclude_none=True)
```

## Dependencies

- `pydantic`: Data validation and settings management
- `typing`: Type hints (Literal, Any, Union)

## Integration with Other Modules

| Module | Usage |
|--------|-------|
| `config/loader.py` | Loads JSON into InverterConfig instances |
| `core/sofar_client.py` | Uses models for type-safe register access |
| `mqtt/discovery.py` | Extracts HA config from register models |
| `transformations/converter.py` | Uses function/type fields for conversions |
