# Sofar2MQTT - Project Documentation

## Project Type

**Sofar2MQTT** is a Python-based IoT bridge application that facilitates communication between Sofar solar inverters and MQTT brokers. It serves as a middleware solution for home automation systems, particularly Home Assistant.

### Key Characteristics
- **Type**: IoT Gateway / Protocol Bridge
- **Primary Language**: Python 3.10+
- **Architecture**: Event-driven with polling mechanism
- **Deployment**: Docker container or standalone Python script

## Business Rules

### Core Functionality
1. **Modbus Communication**: Reads and writes data from/to Sofar inverters via RS485 (Modbus RTU protocol at 9600 baud, 8N1)
2. **MQTT Publishing**: Publishes inverter data to MQTT topics for consumption by home automation systems
3. **Home Assistant Auto-Discovery**: Automatically registers devices and sensors in Home Assistant via MQTT discovery protocol
4. **Bidirectional Control**: Supports both reading sensor data and writing configuration values to the inverter

### Data Flow
1. Poll inverter registers at configurable intervals (default: 10 seconds)
2. Apply transformations to raw Modbus values (scaling, mode mapping, bit field extraction)
3. Publish transformed data to MQTT topics:
   - `sofar/state_all` - Complete state as JSON (primary)
   - `sofar/<sensor_name>` - Individual sensor values (legacy mode)
4. Listen for write commands on `sofar/rw/<register_name>` topics

### Inverter Compatibility
- Sofar ME3000 (battery storage)
- Sofar HYD 3~6 EP (hybrid inverters)
- Extensible to other Sofar models via JSON configuration

### Configuration Model
- Inverter-specific configurations stored as JSON files in `config/` directory
- Each configuration defines:
  - Register addresses and data types (U16, I16, U32, I32)
  - Transformation functions (multiply, divide, mode, bit_field, etc.)
  - Home Assistant discovery metadata
  - Read/write permissions and constraints

## Global Structure

```
sofar2mqtt-python/
├── AGENTS.md                    # This file - project documentation
├── README.md                    # User-facing documentation
├── pyproject.toml              # Python project configuration
├── Dockerfile                  # Container build instructions
├── requirements.txt            # Runtime dependencies
├── requirements-dev.txt        # Development dependencies
│
├── config/                     # Inverter configuration files (JSON)
│   └── SOFAR-*.json           # Model-specific register definitions
│
├── docs/                       # Technical documentation
│   └── *.pdf                  # Protocol specifications
│
├── ha/                         # Home Assistant integration files
│   ├── automations-*.yaml     # Example automation rules
│   └── mqtt-*.yaml            # Legacy MQTT configuration
│
├── img/                        # Documentation images
│
├── systemd/                    # Systemd service configuration
│   └── sofar2mqtt.service     # Linux service definition
│
├── tests/                      # Unit and integration tests
│   ├── conftest.py            # Pytest fixtures
│   └── test_*.py              # Test modules
│
└── sofar2mqtt/                 # Main application package
    ├── __init__.py            # Package initialization
    ├── __main__.py            # Entry point for python -m sofar2mqtt
    ├── cli.py                 # Click-based CLI interface
    │
    ├── config/                # Configuration loading module
    │   └── loader.py          # JSON config parsing and validation
    │
    ├── core/                  # Core communication modules
    │   ├── modbus_client.py   # Modbus RTU client (minimalmodbus wrapper)
    │   └── sofar_client.py    # Main orchestrator class
    │
    ├── mqtt/                  # MQTT integration modules
    │   ├── client.py          # MQTT client wrapper
    │   └── discovery.py       # Home Assistant auto-discovery
    │
    ├── models/                # Pydantic data models
    │   ├── inverter_config.py # Inverter configuration model
    │   └── register.py        # Register definition models
    │
    ├── transformations/       # Data transformation utilities
    │   └── converter.py       # Value conversion functions
    │
    └── utils/                 # Utility modules
        ├── logging_config.py  # Logging configuration
        └── retry.py           # Retry logic utilities
```

## Module Responsibilities

### [`sofar2mqtt/cli.py`](sofar2mqtt/cli.py)
Command-line interface using Click. Handles argument parsing, environment variable configuration, and initializes the main client.

### [`sofar2mqtt/core/`](sofar2mqtt/core/)
Core communication layer:
- **ModbusClient**: Thread-safe Modbus RTU client with retry logic
- **SofarClient**: Main orchestrator coordinating polling, transformation, and publishing

### [`sofar2mqtt/config/`](sofar2mqtt/config/)
Configuration management:
- Loads and validates JSON configuration files
- Maps raw register definitions to Pydantic models

### [`sofar2mqtt/mqtt/`](sofar2mqtt/mqtt/)
MQTT integration:
- Manages MQTT client lifecycle and message handling
- Implements Home Assistant MQTT auto-discovery protocol

### [`sofar2mqtt/models/`](sofar2mqtt/models/)
Data models using Pydantic:
- `InverterConfig`: Complete inverter configuration
- `RegisterDefinition`: Individual register metadata
- `HomeAssistantConfig`: HA discovery payload structure

### [`sofar2mqtt/transformations/`](sofar2mqtt/transformations/)
Data transformation logic:
- `ValueConverter`: Converts between raw Modbus values and human-readable formats
- Supports: scaling, mode mapping, bit field extraction, string parsing

## Development Guidelines

### Dependencies
- **Runtime**: click, paho-mqtt, minimalmodbus, pyserial, pydantic, requests
- **Development**: pytest, pytest-cov, ruff, mypy, pylint

### Code Quality
- Type hints encouraged (mypy configured with `disallow_untyped_defs = false`)
- Linting via ruff (config in `ruff.toml`)
- Tests run with pytest and coverage reporting

### Testing Strategy
- Unit tests for transformation logic
- Mock-based tests for Modbus and MQTT clients
- Integration tests for end-to-end flow

## Deployment Options

### Docker (Recommended)
```bash
docker build -t sofar2mqtt .
docker run -d \
  --device=/dev/ttyUSB0 \
  -e CONFIG_FILE=SOFAR-HYD-ES-AND-ME3000-SP.json \
  -e MQTT_HOST=your-broker \
  sofar2mqtt
```

### Systemd Service
Copy `systemd/sofar2mqtt.service` to `/etc/systemd/system/` and configure environment variables.

### Standalone
```bash
pip install -r requirements.txt
sofar2mqtt --config config/SOFAR-HYD-ES-AND-ME3000-SP.json --broker localhost
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CONFIG_FILE` | (required) | Path to inverter configuration JSON |
| `MQTT_HOST` | localhost | MQTT broker address |
| `MQTT_PORT` | 1883 | MQTT broker port |
| `MQTT_USERNAME` | - | MQTT username (optional) |
| `MQTT_PASSWORD` | - | MQTT password (optional) |
| `TTY_DEVICE` | /dev/ttyUSB0 | RS485 device path |
| `REFRESH_INTERVAL` | 10 | Polling interval in seconds |
| `LOG_LEVEL` | INFO | Logging level (DEBUG/INFO/WARNING/ERROR) |
