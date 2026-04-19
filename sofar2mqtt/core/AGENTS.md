.# sofar2mqtt/core/ - Core Communication Layer

## Module Purpose

This module contains the core communication logic for interacting with Sofar inverters via Modbus RTU and publishing data to MQTT brokers. It serves as the central orchestrator of all hardware and network communications.

## Key Components

### [`sofar_client.py`](sofar_client.py)
The main orchestrator class that coordinates all operations:

**Responsibilities:**
- Initializes and manages ModbusClient and MQTT client instances
- Implements the main polling loop for reading inverter data
- Handles bidirectional communication (read sensors, write configurations)
- Manages Home Assistant auto-discovery payloads
- Coordinates data transformation before publishing

**Key Methods:**
- `__init__()`: Initialize clients with configuration
- `run()`: Main polling loop (runs indefinitely)
- `read_registers()`: Poll inverter and publish to MQTT
- `write_register(register_name, value)`: Write configuration values
- `on_mqtt_message()`: Handle incoming MQTT write commands

### [`modbus_client.py`](modbus_client.py)
Thread-safe Modbus RTU client wrapper around `minimalmodbus`:

**Responsibilities:**
- Serial port management (open/close, baud rate 9600 8N1)
- Register read/write operations with retry logic
- Error handling and reconnection strategies
- Thread-safe access to shared serial port

**Key Features:**
- Automatic retry on communication failures (configurable attempts)
- Timeout handling for slow responses
- Lock-based thread safety for concurrent access

### [`utils.py`](utils.py)
Utility functions used across the core module:

**Functions:**
- `calculate_crc()`: CRC calculation for Modbus frames (if needed)
- `format_timestamp()`: ISO 8601 timestamp formatting
- `parse_serial_response()`: Raw byte parsing utilities

## Data Flow

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  Inverter   │◄───►│ ModbusClient │     │    MQTT     │
│  (RS485)    │     │              │◄───►│   Broker    │
└─────────────┘     └──────┬───────┘     └─────────────┘
                           │
                    ┌──────▼───────┐
                    │ SofarClient  │
                    │ (Orchestrator)│
                    └──────────────┘
```

1. **Read Cycle:**
   - SofarClient triggers poll at configured interval
   - ModbusClient reads register values from inverter
   - Values transformed via `transformations/converter.py`
   - Data published to MQTT topics

2. **Write Cycle:**
   - MQTT message received on `sofar/rw/<register>` topic
   - SofarClient validates write permissions
   - ModbusClient writes value to inverter register
   - Confirmation published back to MQTT

## Error Handling Strategy

- **Modbus Errors**: Retry with exponential backoff, log warnings
- **MQTT Disconnection**: Auto-reconnect with persistent session
- **Invalid Data**: Skip transformation, log error, continue polling
- **Configuration Errors**: Fail fast at startup with clear messages

## Thread Safety Considerations

- ModbusClient uses threading locks for serial port access
- MQTT callbacks run in separate thread (paho-mqtt default)
- Shared state protected by locks where necessary
- Polling loop runs in main thread

## Testing Guidelines

- Mock ModbusClient for unit tests (use `unittest.mock`)
- Use test MQTT broker (e.g., testcontainers) for integration tests
- Test retry logic with simulated failures
- Verify thread safety with concurrent access patterns

## Dependencies

- `minimalmodbus`: Modbus RTU protocol implementation
- `pyserial`: Serial port communication
- `paho-mqtt`: MQTT client library
- `threading`: Thread synchronization primitives
