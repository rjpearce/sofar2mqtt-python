# sofar2mqtt/utils/ - Utility Modules

## Module Purpose

This module contains shared utility functions and utilities used across the application. These are cross-cutting concerns that don't fit into specific domain modules but are essential for the application's operation.

## Key Components

### [`logging_config.py`](logging_config.py)
Logging configuration utility:

**Function: `setup_logging(level: str, log_file: str | None) -> None`**

Configures Python's logging system with consistent formatting and handlers.

**Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `level` | str | "INFO" | Log level (DEBUG, INFO, WARNING, ERROR) |
| `log_file` | str \| None | None | Optional file path for log output |

**Behavior:**
- Creates console handler (stdout)
- Optionally creates file handler if `log_file` provided
- Sets log format: `%(asctime)s [%(levelname)s] %(name)s: %(message)s`
- Date format: `YYYY-MM-DD HH:MM:SS`

**Example Usage:**

```python
from sofar2mqtt.utils.logging_config import setup_logging

# Console only, INFO level
setup_logging(level="INFO")

# Console and file, DEBUG level
setup_logging(level="DEBUG", log_file="/var/log/sofar2mqtt.log")
```

**Log Output Example:**

```
2024-01-15 10:30:45 [INFO] sofar2mqtt.core.sofar_client: Starting sofar2mqtt 4.0.1
2024-01-15 10:30:46 [DEBUG] sofar2mqtt.core.modbus_client: Reading register 0x1000
2024-01-15 10:30:47 [WARNING] sofar2mqtt.mqtt.client: MQTT connecting without auth
2024-01-15 10:30:48 [ERROR] sofar2mqtt.core.sofar_client: Failed to read register
```

### [`retry.py`](retry.py)
Retry logic utilities:

**Decorator: `retry_on_failure(max_retries, delay, exceptions)`**

Decorator for retrying operations on failure with configurable attempts and delay.

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `max_retries` | int | Maximum number of retry attempts |
| `delay` | float | Delay between retries in seconds |
| `exceptions` | tuple | Tuple of exception types to catch |

**Returns:**
- Decorated function with retry logic applied

**Behavior:**
- Attempts function execution up to `max_retries + 1` times
- Logs debug message on each failed attempt
- Logs error message after all retries exhausted
- Raises last exception if all retries fail

**Example Usage:**

```python
from sofar2mqtt.utils.retry import retry_on_failure
from minimalmodbus import NoResponseError, SerialException

@retry_on_failure(3, 0.1, (NoResponseError, SerialException))
def read_register(instrument, addr):
    return instrument.read_register(addr)
```

**Log Output on Failure:**

```
DEBUG: sofar2mqtt.core.modbus_client: read_register failed (attempt 1/3): No response from inverter
DEBUG: sofar2mqtt.core.modbus_client: read_register failed (attempt 2/3): No response from inverter
ERROR: sofar2mqtt.core.modbus_client: read_register failed after 3 attempts: No response from inverter
```

## Design Patterns

### Utility Module Structure

```
utils/
├── __init__.py          # Package initialization
├── logging_config.py    # Logging setup
└── retry.py             # Retry decorator
```

### Cross-Cutting Concerns

These utilities address concerns that span multiple modules:

| Concern | Module | Usage |
|---------|--------|-------|
| Logging | All | Consistent log format across application |
| Retry | core/modbus_client | Handle transient Modbus failures |

## Integration with Other Modules

### sofar2mqtt/cli.py

```python
from sofar2mqtt.utils.logging_config import setup_logging

# Configure logging at application startup
setup_logging(level=log_level)
```

### sofar2mqtt/core/modbus_client.py

```python
from sofar2mqtt.utils.retry import retry_on_failure

@retry_on_failure(max_retries, delay, (NoResponseError, SerialException))
def read_register(self, addr):
    return self.instrument.read_register(addr)
```

## Best Practices

### Logging

1. **Use appropriate log levels:**
   - `DEBUG`: Detailed diagnostic information for troubleshooting
   - `INFO`: Normal operational messages
   - `WARNING`: Unexpected but not fatal events
   - `ERROR`: Error conditions that may affect functionality

2. **Include context in messages:**
   - Register addresses
   - Values being read/written
   - Connection details

3. **Avoid logging sensitive data:**
   - Passwords
   - Private keys
   - Personal information

### Retry Logic

1. **Choose appropriate retry counts:**
   - Network operations: 3-5 retries
   - Serial port: 2-3 retries
   - Critical operations: More retries with longer delays

2. **Set reasonable delays:**
   - Fast operations: 0.1-0.5 seconds
   - Network operations: 1-5 seconds
   - Hardware operations: 0.5-2 seconds

3. **Catch specific exceptions:**
   - Only retry transient failures
   - Don't retry programming errors (ValueError, TypeError)
   - Don't retry permanent failures (FileNotFoundError)

## Testing Guidelines

### Testing Logging Configuration

```python
def test_setup_logging_console(caplog):
    setup_logging(level="DEBUG")
    assert logging.getLogger().level == logging.DEBUG

def test_setup_logging_file(tmp_path):
    log_file = tmp_path / "test.log"
    setup_logging(level="INFO", log_file=str(log_file))
    assert log_file.exists()
```

### Testing Retry Decorator

```python
def test_retry_succeeds_on_first_attempt():
    call_count = 0

    @retry_on_failure(3, 0.1, (ValueError,))
    def always_succeeds():
        return "success"

    result = always_succeeds()
    assert result == "success"

def test_retry_fails_after_max_attempts():
    call_count = 0

    @retry_on_failure(2, 0.01, (ValueError,))
    def always_fails():
        nonlocal call_count
        call_count += 1
        raise ValueError("always fails")

    with pytest.raises(ValueError):
        always_fails()

    assert call_count == 3  # Initial + 2 retries
```

## Dependencies

### Runtime
- `logging`: Python standard library
- `time`: Python standard library
- `functools`: Python standard library (wraps decorator)
- `typing`: Type hints (Callable, TypeVar, Any)

### No External Dependencies
These utilities use only Python standard library modules.

## Future Enhancements

Potential additions to the utils module:

1. **Configuration validation utilities**
   - Schema validation helpers
   - Default value merging

2. **Performance monitoring**
   - Timing decorators
   - Memory usage tracking

3. **Health check utilities**
   - Connectivity checkers
   - Status aggregation

4. **Serialization utilities**
   - Custom JSON encoders
   - YAML support
