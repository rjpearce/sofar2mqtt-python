"""Modbus communication client for Sofar inverters."""

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

import serial
from minimalmodbus import Instrument, InvalidResponseError, NoResponseError

logger = logging.getLogger(__name__)


class ModbusClient:
    """Thread-safe Modbus client for Sofar inverter communication."""

    def __init__(
        self,
        device: str,
        slave_id: int = 1,
        retry: int = 2,
        retry_delay: float = 0.1,
    ):
        """Initialize Modbus client."""
        self.device = device
        self.slave_id = slave_id
        self.retry = retry
        self.retry_delay = retry_delay
        self.instrument: Instrument | None = None
        self._mutex = threading.Lock()

    def setup(self) -> None:
        """Initialize the Modbus instrument."""
        with self._mutex:
            self.instrument = Instrument(self.device, self.slave_id)
            self.instrument.serial.baudrate = 9600
            self.instrument.serial.parity = serial.PARITY_NONE
            self.instrument.serial.stopbits = serial.STOPBITS_ONE
            self.instrument.serial.bytesize = serial.EIGHTBITS
            self.instrument.serial.timeout = 1.0
            # Close the port between calls: the inverter does not reliably accept
            # a write command right after read commands on an open port.
            self.instrument.close_port_after_each_call = True
            # minimalmodbus uses MODE_RTU by default, no need to set explicitly
            logger.debug(f"Modbus instrument configured for {self.device}")

    def _check_initialized(self) -> bool:
        """Check if instrument is initialized."""
        if not self.instrument:
            logger.error("Modbus instrument not initialized")
            return False
        return True

    def _execute_with_retry(
        self,
        operation: Callable[[], Any],
        error_msg: str,
        default: Any = None,
    ) -> Any:
        """Execute an operation with retry logic."""
        retry_count = self.retry
        while retry_count > 0:
            try:
                return operation()
            except (NoResponseError, InvalidResponseError, serial.SerialException) as e:
                retry_count -= 1
                if retry_count > 0:
                    logger.debug(f"{error_msg}, retrying... ({retry_count} left)")
                    time.sleep(self.retry_delay)
                else:
                    logger.error(f"{error_msg}: {e}")
        return default

    def read_register(
        self,
        register_address: int,
        function_code: int = 3,
        signed: bool = True,
    ) -> int | None:
        """Read a single register with retry logic."""
        with self._mutex:
            if not self._check_initialized():
                return None

            def operation():
                return self.instrument.read_register(
                    register_address,
                    functioncode=function_code,
                    signed=signed,
                )

            return self._execute_with_retry(
                operation,
                f"Failed to read register 0x{register_address:04X}",
            )

    def read_long(self, register_address: int, signed: bool = True) -> int | None:
        """Read a 32-bit value from two consecutive registers."""
        with self._mutex:
            if not self._check_initialized():
                return None

            def operation():
                return self.instrument.read_long(
                    register_address,
                    signed=signed,
                )

            return self._execute_with_retry(
                operation,
                f"Failed to read long at 0x{register_address:04X}",
            )

    def read_string(self, register_address: int, count: int = 16) -> str | None:
        """Read a string from consecutive registers."""
        with self._mutex:
            if not self._check_initialized():
                return None

            def operation():
                return self.instrument.read_string(
                    register_address,
                    count,
                )

            return self._execute_with_retry(
                operation,
                f"Failed to read string at 0x{register_address:04X}",
            )

    def write_register(self, register_address: int, value: int) -> bool:
        """Write a value to a single register with retry logic."""
        with self._mutex:
            if not self._check_initialized():
                return False

            def operation():
                self.instrument.write_register(
                    register_address,
                    int(value),
                )
                return True

            return self._execute_with_retry(
                operation,
                f"Failed to write register 0x{register_address:04X}",
                default=False,
            )

    def write_registers(self, start_address: int, values: list[int]) -> bool:
        """Write multiple consecutive registers with retry logic."""
        with self._mutex:
            if not self._check_initialized():
                return False

            def operation():
                self.instrument.write_registers(start_address, values)
                return True

            return self._execute_with_retry(
                operation,
                f"Failed to write registers at 0x{start_address:04X}",
                default=False,
            )

    def write_register_special(
        self, register_address: int, function_code: int, value: int
    ) -> bytes | None:
        """Write using a special/proprietary function code."""
        import struct

        with self._mutex:
            if not self._check_initialized():
                return None

            def operation():
                payload = struct.pack(">H", register_address) + struct.pack(">H", value)
                return self.instrument._perform_command(function_code, payload)

            return self._execute_with_retry(
                operation,
                "Special write failed",
            )

    def read_ascii(self, start_address: int, count: int) -> str | None:
        """Read ASCII string from consecutive registers."""
        with self._mutex:
            if not self._check_initialized():
                return None

            def operation():
                regs = self.instrument.read_registers(start_address, count, functioncode=3)
                chars = []
                for reg in regs:
                    # Convert register to 2 ASCII characters
                    chars.append(chr((reg >> 8) & 0xFF))
                    chars.append(chr(reg & 0xFF))
                return "".join(chars).rstrip("\x00")

            return self._execute_with_retry(
                operation,
                f"Failed to read ASCII at 0x{start_address:04X}",
            )

    def read_holding_registers(self, start_address: int, num_registers: int) -> list[int] | None:
        """Read multiple holding registers with retry logic."""
        with self._mutex:
            if not self._check_initialized():
                return None

            def operation():
                return self.instrument.read_registers(start_address, num_registers, functioncode=3)

            return self._execute_with_retry(
                operation,
                f"Failed to read holding registers at 0x{start_address:04X}",
            )

    def read_input_registers(self, start_address: int, num_registers: int) -> list[int] | None:
        """Read multiple input registers with retry logic."""
        with self._mutex:
            if not self._check_initialized():
                return None

            def operation():
                return self.instrument.read_registers(start_address, num_registers, functioncode=4)

            return self._execute_with_retry(
                operation,
                f"Failed to read input registers at 0x{start_address:04X}",
            )

    def close(self) -> None:
        """Close the Modbus connection."""
        with self._mutex:
            if self.instrument and self.instrument.serial.is_open:
                self.instrument.serial.close()
                logger.debug("Modbus connection closed")
