"""Data models for Sofar2MQTT register definitions."""

from typing import Optional, Dict, Any, List, Literal
from pydantic import BaseModel, Field


class HomeAssistantConfig(BaseModel):
    """Home Assistant auto-discovery configuration."""

    name: Optional[str] = None
    object_id: Optional[str] = None
    unique_id: Optional[str] = None
    device_class: Optional[str] = None
    entity_category: Optional[str] = None
    state_class: Optional[str] = None
    unit_of_measurement: Optional[str] = None
    icon: Optional[str] = None
    value_template: Optional[str] = None
    command_topic: Optional[str] = None
    state_topic: Optional[str] = None
    control: Optional[Literal["number", "select", "text"]] = None
    min: Optional[float] = None
    max: Optional[float] = None
    step: Optional[float] = None
    mode: Optional[Literal["slider", "box"]] = None
    initial: Optional[float] = None
    enabled_by_default: bool = True
    options: Optional[List[str]] = None

    class Config:
        extra = "allow"


class RegisterDefinition(BaseModel):
    """Definition of a Modbus register."""

    name: str
    register: Optional[str] = None  # Hex address like "0x1234"
    read_type: Literal["register", "long", "string", "static"] = "register"
    type: Optional[Literal["U16", "I16", "U32", "I32"]] = None
    function: Optional[
        Literal[
            "multiply",
            "divide",
            "mode",
            "bit_field",
            "high_bit_low_bit",
            "int",
            "history_event_map",
        ]
    ] = None
    factor: Optional[float] = None
    modes: Optional[Dict[str, str]] = None
    fields: Optional[List[str]] = None
    join: Optional[str] = None
    min: Optional[float] = None
    max: Optional[float] = None
    signed: bool = False
    write: bool = False
    read: bool = True
    refresh: int = 1  # Read every N iterations
    notify_on_change: bool = False
    ha: Optional[HomeAssistantConfig] = None
    desc: Optional[str] = None

    # Special configurations
    aggregate: Optional[List[str]] = None  # For combining multiple registers
    agg_function: Optional[Literal["add", "subtract", "avg"]] = None
    aggregate_datetime_bitmap: Optional[Dict[str, str]] = None

    # Write-specific configurations
    write_addresses: Optional[Dict[str, str]] = None
    write_values: Optional[Dict[str, Any]] = None
    write_functioncode: Optional[str] = None
    passive: bool = False  # Don't poll this register
    untested: bool = False  # Track registers not tested

    # Static values
    value: Optional[Any] = None

    class Config:
        extra = "allow"

    def model_dump(self, **kwargs):
        """Override to ensure proper serialization."""
        return super().model_dump(**kwargs)


class WriteRegisterBlock(BaseModel):
    """Definition of a block of registers to write together."""

    name: str
    start_register: str  # Starting hex address
    length: int  # Number of registers in the block
    registers: List[str]  # List of register names
    append: Optional[List[int]] = None  # Values to append at the end


# InverterConfig is defined in inverter_config.py to avoid circular imports
