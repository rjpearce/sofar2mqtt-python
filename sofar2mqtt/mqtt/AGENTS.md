# sofar2mqtt/mqtt/ - MQTT Integration

## Module Purpose

This module handles all MQTT communication, including client management and Home Assistant auto-discovery. It provides the bridge between the inverter data and home automation systems.

## Key Components

### [`client.py`](client.py)
MQTT client wrapper around `paho-mqtt`:

**Responsibilities:**
- Encapsulates paho-mqtt client functionality
- Manages broker connection and authentication
- Handles TLS configuration for secure connections
- Provides thread-safe publish/subscribe operations
- Implements Last Will Testament for connectivity monitoring

**Key Methods:**
- `__init__()`: Initialize with broker settings and optional credentials
- `setup()`: Configure authentication and TLS if needed
- `connect(clean_start)`: Establish connection to MQTT broker
- `subscribe(topic, qos)`: Subscribe to MQTT topics
- `publish(topic, payload, qos, retain)`: Publish messages to topics
- `disconnect()`: Gracefully disconnect from broker

**Callback Handlers:**
- `set_on_connect(callback)`: Set connection event handler
- `set_on_message(callback)`: Set message received handler
- `set_on_disconnect(callback)`: Set disconnection handler

### [`discovery.py`](discovery.py)
Home Assistant MQTT auto-discovery implementation:

**Responsibilities:**
- Publishes device discovery payloads to Home Assistant
- Creates sensor, number, and select entity configurations
- Manages bridge connectivity status sensor
- Builds device information for inverter registration

**Key Classes:**
- `HomeAssistantDiscovery`: Main discovery manager class

**Key Methods:**
- `__init__(mqtt_client, serial_number)`: Initialize with MQTT client and device serial
- `publish_bridge_status()`: Publish bridge connectivity sensor
- `discover_all(registers, device_id, device_name)`: Publish discovery for all registers
- `publish_register_discovery(register, device_info)`: Publish single register discovery

**Helper Functions:**
- `build_device_info(config, raw_data)`: Construct device information payload

## MQTT Topic Structure

### Published Topics
| Topic | Description |
|-------|-------------|
| `sofar/state_all` | Complete inverter state as JSON |
| `sofar/<sensor_name>` | Individual sensor values (legacy) |
| `sofar2mqtt_python/bridge` | Bridge connectivity status |

### Subscribed Topics
| Topic | Description |
|-------|-------------|
| `sofar/rw/<register_name>` | Write commands for configurable registers |

### Home Assistant Discovery Topics
| Pattern | Description |
|---------|-------------|
| `homeassistant/binary_sensor/{serial}/connection_state/config` | Bridge status sensor |
| `homeassistant/sensor/{register_name}/config` | Sensor entities |
| `homeassistant/number/{register_name}/config` | Writable number entities |
| `homeassistant/select/{register_name}/config` | Writable select entities |

## Discovery Payload Structure

```json
{
  "name": "Display Name",
  "state_topic": "sofar/state_all",
  "unique_id": "serial_register_name",
  "device": {
    "name": "Sofar Inverter",
    "manufacturer": "Sofar",
    "model": "HYD-EP",
    "sw_version": "unknown",
    "hw_version": "unknown",
    "configuration_url": "https://github.com/rjpearce/sofar2mqtt-python"
  },
  "availability": [{"topic": "sofar2mqtt_python/bridge", "value_template": "online"}],
  "device_class": "power",
  "unit_of_measurement": "W",
  "state_class": "measurement"
}
```

## Connection Lifecycle

```
1. Setup
   ├── Configure authentication (username/password)
   └── Configure TLS (if CA certs provided)

2. Connect
   ├── Establish TCP connection
   ├── Send MQTT CONNECT
   └── Start network loop thread

3. Runtime
   ├── Publish state updates
   ├── Subscribe to write command topics
   └── Handle incoming messages

4. Disconnect
   ├── Publish offline status (LWT)
   └── Clean up network resources
```

## Error Handling

- **Connection Failures**: Automatic reconnection with exponential backoff
- **Publish Failures**: Logged as errors, non-fatal (continues operation)
- **Discovery Errors**: Logged per-register, continues with remaining registers
- **TLS Errors**: Logged with warnings if port mismatch detected

## Dependencies

- `paho-mqtt`: MQTT client library (v1.x or v2.x)
- `json`: Standard library for payload serialization

## Integration with Other Modules

| Module | Interaction |
|--------|-------------|
| `core/sofar_client.py` | Receives MQTT client instance, sets up callbacks |
| `config/loader.py` | Reads HA discovery metadata from register configs |
| `transformations/converter.py` | Transformed values published as MQTT payloads |
