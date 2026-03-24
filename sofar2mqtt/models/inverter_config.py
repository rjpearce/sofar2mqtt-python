"""Inverter configuration model."""

from typing import Any

from pydantic import BaseModel

from sofar2mqtt.models.register import RegisterDefinition, WriteRegisterBlock


class InverterConfig(BaseModel):
    """Complete inverter configuration from JSON file."""

    registers: list[RegisterDefinition]
    write_register_blocks: list[WriteRegisterBlock] | None = None
    error_codes: dict[str, Any] | None = None

    class Config:
        extra = "allow"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InverterConfig":
        """Create InverterConfig from dictionary."""
        return cls(**data)


__all__ = ["InverterConfig"]
