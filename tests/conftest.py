"""Pytest fixtures and configuration."""

import pytest
import json
from pathlib import Path
from unittest.mock import MagicMock, Mock

BASE_DIR = Path(__file__).parent.parent
CONFIG_DIR = BASE_DIR / "config"


@pytest.fixture
def sample_config_3ph():
    """Load 3-phase inverter config."""
    path = CONFIG_DIR / "SOFAR-HYD-3PH-AND-G3.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return None


@pytest.fixture
def sample_config_es():
    """Load ES inverter config."""
    path = CONFIG_DIR / "SOFAR-HYD-ES-AND-ME3000-SP.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return None


@pytest.fixture
def mock_mqtt_client():
    """Create a mock MQTT client."""
    client = MagicMock()
    client.connected = True
    return client


@pytest.fixture
def mock_modbus_instrument():
    """Create a mock Modbus instrument."""
    instrument = MagicMock()

    instrument.read_register = MagicMock(return_value=1234)
    instrument.write_register = MagicMock(return_value=None)
    instrument.read_registers = MagicMock(return_value=bytearray(b"\x00\x00"))
    return instrument


@pytest.fixture
def mock_modbus(mock_modbus_instrument):
    """Alias for mock_modbus_instrument fixture."""
    return mock_modbus_instrument


@pytest.fixture
def mock_converter():
    """Create a mock ValueConverter."""
    converter = MagicMock()
    converter.from_raw = MagicMock(side_effect=lambda r, v: float(v) if v is not None else None)
    converter.to_raw = MagicMock(side_effect=lambda r, v: int(v) if v is not None else 0)
    converter.validate = MagicMock(return_value=True)
    return converter


@pytest.fixture(autouse=True)
def setup_logging():
    """Configure logging for tests."""
    import logging

    logging.basicConfig(level=logging.WARNING)
    return logging
