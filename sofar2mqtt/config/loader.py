"""Configuration loader for Sofar2MQTT."""

import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional

from sofar2mqtt.models.inverter_config import InverterConfig

logger = logging.getLogger(__name__)


def load_config(config_path: str) -> InverterConfig:
    """Load and validate configuration from JSON file.

    Args:
        config_path: Path to JSON configuration file

    Returns:
        Validated InverterConfig model
    """
    path = Path(config_path)

    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    logger.info(f"Loading configuration from {config_path}")

    with open(path, "r", encoding="utf-8") as f:
        config_dict = json.load(f)

    # Validate required fields
    if "registers" not in config_dict:
        raise ValueError("Configuration must contain 'registers' key")

    # Create InverterConfig model
    return InverterConfig.from_dict(config_dict)


class ConfigLoader:
    """Loads and validates inverter configuration from JSON files."""

    def __init__(self, config_path: str):
        """Initialize config loader with path to configuration file."""
        self.config_path = Path(config_path)

    def load(self) -> InverterConfig:
        """
        Load configuration from JSON file.

        Returns:
            Dictionary containing configuration data

        Raises:
            FileNotFoundError: If config file doesn't exist
            json.JSONDecodeError: If JSON is invalid
        """
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config file not found: {self.config_path}")

        logger.info(f"Loading configuration from {self.config_path}")

        with open(self.config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        # Validate required fields
        if "registers" not in config:
            raise ValueError("Configuration must contain 'registers' key")

        # Log validation warnings
        self._validate_registers(config["registers"])

        return config

    @staticmethod
    def _validate_registers(registers: list) -> None:
        """Validate register definitions and log warnings for issues."""
        issues = {"missing_type": 0, "function_no_type": 0, "none_values": 0, "duplicates": set()}

        seen_names = {}

        for i, reg in enumerate(registers):
            name = reg.get("name", f"unnamed_{i}")

            # Check for duplicates
            if name in seen_names:
                issues["duplicates"].add(name)
                logger.warning(
                    f"Duplicate register name '{name}': "
                    f"first at index {seen_names[name]}, duplicate at index {i}"
                )
            else:
                seen_names[name] = i

            # Check for missing type when it might be needed
            if "type" not in reg and "read_type" not in reg:
                issues["missing_type"] += 1

            # Check for function without type (will default to U16)
            if "function" in reg and "type" not in reg:
                issues["function_no_type"] += 1
                logger.debug(
                    f"Register '{name}' has function '{reg['function']}' but no type - "
                    f"will default to U16"
                )

            # Check for None/TBD placeholder values
            if reg.get("value") in [None, "TBD", "tbd"]:
                issues["none_values"] += 1

        # Log summary warnings
        if issues["missing_type"] > 0:
            logger.warning(f"Found {issues['missing_type']} registers without type/read_type field")

        if issues["function_no_type"] > 0:
            logger.warning(
                f"Found {issues['function_no_type']} registers with function but no type"
            )

        if issues["none_values"] > 0:
            logger.warning(
                f"Found {issues['none_values']} registers with None/TBD placeholder values"
            )

    @staticmethod
    def load_from_file(config_path: str) -> Dict[str, Any]:
        """
        Static convenience method to load config from file path.

        Args:
            config_path: Path to JSON configuration file

        Returns:
            Configuration dictionary
        """
        loader = ConfigLoader(config_path)
        return loader.load()
