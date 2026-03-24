"""Modbus communication client for Sofar inverters."""

import logging
import threading
import time

import serial
from minimalmodbus import Instrument, InvalidResponseError, NoResponseError

logger = logging.getLogger(__name__)


class ModbusClient:
    """Thread-safe Modbus client for Sofar inverter communication."""

    def __init__(self, device: str, slave_id: int = 1, retry: int = 2, retry_delay: float = 0.1):
        """Initialize Modbus client."""
        self.device = device
        self.slave_id = slave_id
        self.retry = retry
        self.retry_delay = retry_delay
        self.instrument: Instrument | None = None
        self._mutex = threading.Lock()

    def setup(self) -> None:
        """Configure the Modbus instrument with Sofar-specific settings."""
        with self._mutex:
            self.instrument = Instrument(self.device, self.slave_id)
            self.instrument.serial.baudrate = 9600
            self.instrument.serial.bytesize = 8
            self.instrument.serial.parity = serial.PARITY_NONE
            self.instrument.serial.stopbits = 1
            self.instrument.serial.timeout = 0.5
            self.instrument.close_port_after_each_call = False
            self.instrument.clear_buffers_before_each_transaction = True
            logger.debug(f"Modbus instrument configured for {self.device}")

    def read_register(
        self,
        register_address: int,
        function_code: int = 3,
        signed: bool = False,
        number_of_registers: int = 1,
    ) -> int | None:
        """Read a single register with retry logic."""
        with self._mutex:
            if not self.instrument:
                logger.error("Modbus instrument not initialized")
                return None

            value = None
            retry_count = self.retry

            while retry_count > 0 and value is None:
                try:
                    if function_code == 3:
                        value = self.instrument.read_register(
                            register_address,
                            number_of_decimals=0,
                            functioncode=function_code,
                            signed=signed,
                        )
                    elif function_code == 4:
                        value = self.instrument.read_input_registers(
                            register_address,
                            number_of_registers,
                            functioncode=function_code,
                            signed=signed,
                        )
                except (NoResponseError, InvalidResponseError, serial.SerialException):
                    retry_count -= 1
                    if retry_count > 0:
                        logger.debug(f"Read failed, retrying... ({retry_count} left)")
                        time.sleep(self.retry_delay)

            if value is None:
                logger.error(f"Failed to read register 0x{register_address:04X}")

            return value

    def read_long(self, register_address: int, signed: bool = True) -> int | None:
        """Read a 32-bit long value (2 registers)."""
        with self._mutex:
            if not self.instrument:
                logger.error("Modbus instrument not initialized")
                return None

            try:
                value = self.instrument.read_long(
                    register_address, functioncode=3, signed=signed, number_of_registers=2
                )
                return value
            except (NoResponseError, InvalidResponseError, serial.SerialException) as e:
                logger.error(f"Failed to read long at 0x{register_address:04X}: {e}")
                return None

    def read_string(self, register_address: int, number_of_registers: int = 1) -> str | None:
        """Read a string value from multiple registers."""
        with self._mutex:
            if not self.instrument:
                logger.error("Modbus instrument not initialized")
                return None

            try:
                value = self.instrument.read_string(
                    register_address, functioncode=3, number_of_registers=number_of_registers
                )
                return value
            except (NoResponseError, InvalidResponseError, serial.SerialException) as e:
                logger.error(f"Failed to read string at 0x{register_address:04X}: {e}")
                return None

    def write_register(self, register_address: int, value: int) -> bool:
        """Write a value to a single register with retry logic."""
        with self._mutex:
            if not self.instrument:
                logger.error("Modbus instrument not initialized")
                return False

            retry_count = self.retry
            success = False

            while retry_count > 0 and not success:
                try:
                    self.instrument.write_register(register_address, int(value), functioncode=6)
                    success = True
                    logger.debug(f"Successfully wrote 0x{register_address:04X} = {value}")
                except (NoResponseError, InvalidResponseError, serial.SerialException):
                    retry_count -= 1
                    if retry_count > 0:
                        logger.debug(f"Write failed, retrying... ({retry_count} left)")
                        time.sleep(self.retry_delay)

            if not success:
                logger.error(f"Failed to write register 0x{register_address:04X} = {value}")

            return success

    def write_registers(self, start_address: int, values: list[int]) -> bool:
        """Write multiple consecutive registers with retry logic."""
        with self._mutex:
            if not self.instrument:
                logger.error("Modbus instrument not initialized")
                return False

            retry_count = self.retry
            success = False

            while retry_count > 0 and not success:
                try:
                    self.instrument.write_registers(start_address, values, functioncode=16)
                    success = True
                    logger.debug(f"Successfully wrote registers at 0x{start_address:04X}")
                except (NoResponseError, InvalidResponseError, serial.SerialException):
                    retry_count -= 1
                    if retry_count > 0:
                        logger.debug(f"Write failed, retrying... ({retry_count} left)")
                        time.sleep(self.retry_delay)

            if not success:
                logger.error(f"Failed to write registers at 0x{start_address:04X}")

            return success

    def write_register_special(
        self, register_address: int, function_code: int, value: int
    ) -> bytes | None:
        """Write using a special/proprietary function code."""
        import struct

        with self._mutex:
            if not self.instrument:
                logger.error("Modbus instrument not initialized")
                return None

            try:
                reg_int = (
                    int(register_address, 16)
                    if isinstance(register_address, str)
                    else register_address
                )
                payload = struct.pack(">HH", reg_int, value)

                logger.debug(
                    f"Special write: 0x{reg_int:04X} func=0x{function_code:02X} payload={payload.hex(' ')}"
                )

                response = self.instrument._perform_command(function_code, payload)

                logger.debug(f"Special write response: {response.hex(' ')}")
                return response

            except Exception as e:
                logger.error(f"Special write failed: {e}")
                return None

    def read_ascii(self, start_address: int, count: int) -> str | None:
        """Read ASCII string from consecutive registers."""
        with self._mutex:
            if not self.instrument:
                logger.error("Modbus instrument not initialized")
                return None

            try:
                regs = self.instrument.read_registers(start_address, count, functioncode=3)
            except Exception as e:
                logger.debug(f"Error reading registers at 0x{start_address:04X}: {e}")
                return None

            chars = []
            for val in regs:
                hi = (val >> 8) & 0xFF
                lo = val & 0xFF

                # Sofar stores ASCII in HIGH BYTE first
                for b in (hi, lo):
                    if b == 0:
                        continue
                    c = chr(b)
                    if c.isprintable():
                        chars.append(c)

            return "".join(chars)

    def close(self) -> None:
        """Close the Modbus connection."""
        with self._mutex:
            if self.instrument and self.instrument.serial.is_open:
                self.instrument.serial.close()
                logger.debug("Modbus connection closed")
