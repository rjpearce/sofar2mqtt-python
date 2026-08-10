"""Data models for Sofar2MQTT register definitions."""

from typing import Any, Literal

from pydantic import BaseModel


class HomeAssistantConfig(BaseModel):
    """Home Assistant auto-discovery configuration."""

    name: str | None = None
    object_id: str | None = None
    unique_id: str | None = None
    device_class: str | None = None
    entity_category: str | None = None
    state_class: str | None = None
    unit_of_measurement: str | None = None
    icon: str | None = None
    value_template: str | None = None
    command_topic: str | None = None
    state_topic: str | None = None
    control: Literal["number", "select", "text"] | None = None
    min: float | None = None
    max: float | None = None
    step: float | None = None
    mode: Literal["slider", "box"] | None = None
    initial: float | None = None
    enabled_by_default: bool = True
    options: list[str] | None = None

    class Config:
        extra = "allow"


class RegisterDefinition(BaseModel):
    """Definition of a Modbus register."""

    name: str
    register: str | None = None  # Hex address like "0x1234"
    read_type: Literal["register", "long", "string", "static"] = "register"
    type: Literal["U16", "I16", "U32", "I32"] | None = None
    function: (
        Literal[
            "multiply",
            "divide",
            "mode",
            "bit_field",
            "high_bit_low_bit",
            "int",
            "history_event_map",
        ]
        | None
    ) = None
    factor: float | None = None
    modes: dict[str, str] | None = None
    fields: list[str] | None = None
    join: str | None = None
    min: float | None = None
    max: float | None = None
    signed: bool = False
    write: bool = False
    read: bool = True
    refresh: int = 1  # Read every N iterations
    notify_on_change: bool = False
    ha: HomeAssistantConfig | None = None
    desc: str | None = None

    # Special configurations
    aggregate: list[str] | None = None  # For combining multiple registers
    agg_function: Literal["add", "subtract", "avg"] | None = None
    aggregate_datetime_bitmap: dict[str, str] | None = None

    # Write-specific configurations
    write_addresses: dict[str, str] | None = None
    write_values: dict[str, Any] | None = None
    write_functioncode: str | None = None
    # "standard" = function code 6, "special" = proprietary function code (e.g. 66)
    write_type: Literal["standard", "special"] = "standard"
    passive: bool = False  # Don't poll this register
    untested: bool = False  # Track registers not tested
    sentinel_value: int | None = None  # Value to normalize (e.g., -1 for invalid)

    # Static values
    value: Any | None = None

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
    registers: list[str]  # List of register names
    append: list[int] | None = None  # Values to append at the end


class HeartbeatConfig(BaseModel):
    """Passive-mode heartbeat configuration (function code 0x49, register 0x2201)."""

    enabled: bool = True
    address: str = "0x2201"  # Heartbeat register
    value: str = "0x2202"  # Heartbeat payload value
    function_code: int = 73  # 0x49
    interval: int = 5  # Seconds between heartbeats (1-10 recommended)


# InverterConfig is defined in inverter_config.py to avoid circular imports
