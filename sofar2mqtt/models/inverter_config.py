"""Inverter configuration model."""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel
from sofar2mqtt.models.register import RegisterDefinition, WriteRegisterBlock


class InverterConfig(BaseModel):
    """Complete inverter configuration from JSON file."""

    registers: List[RegisterDefinition]
    write_register_blocks: Optional[List[WriteRegisterBlock]] = None
    error_codes: Optional[Dict[str, Any]] = None

    class Config:
        extra = "allow"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InverterConfig":
        """Create InverterConfig from dictionary."""
        return cls(**data)


__all__ = ["InverterConfig"]
