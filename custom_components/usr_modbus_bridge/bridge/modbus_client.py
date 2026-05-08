"""
TCP → Modbus RTU client.

Maintains a persistent TCP connection to a USR serial-to-ethernet converter.
All Modbus frames are sent as raw bytes over TCP (transparent mode).
Thread-safety: a single asyncio.Lock serialises every request.
"""
from __future__ import annotations
import asyncio
import logging
import struct
from typing import Any

_LOGGER = logging.getLogger(__name__)

_INTER_FRAME_DELAY = 0.05
_CONNECT_TIMEOUT   = 5.0
_READ_TIMEOUT      = 1.0


def _crc16(data: bytes) -> bytes:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return struct.pack("<H", crc)


def _check_crc(data: bytes) -> bool:
    return len(data) >= 3 and _crc16(data[:-2]) == data[-2:]


class ModbusClientError(Exception):
    """Raised when a Modbus transaction fails."""


class ModbusTCPClient:
    """Async Modbus RTU-over-TCP client."""

    def __init__(self, host: str, port: int = 8899, baud: int = 9600) -> None:
        self._host   = host
        self._port   = port
        self._baud   = baud
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock   = asyncio.Lock()
        self._connected = False

    async def connect(self) -> None:
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, self._port),
                timeout=_CONNECT_TIMEOUT,
            )
            self._connected = True
            _LOGGER.debug("Connected to %s:%s", self._host, self._port)
        except (OSError, asyncio.TimeoutError) as err:
            self._connected = False
            raise ModbusClientError(f"Cannot connect to {self._host}:{self._port}: {err}") from err

    async def disconnect(self) -> None:
        self._connected = False
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
            self._reader = None

    async def ensure_connected(self) -> None:
        if not self._connected or self._writer is None:
            await self.connect()

    @property
    def is_connected(self) -> bool:
        return self._connected

    @staticmethod
    def _build_fc03(device_id: int, register: int, count: int = 1) -> bytes:
        payload = struct.pack(">BBHH", device_id, 0x03, register, count)
        return payload + _crc16(payload)

    @staticmethod
    def _build_fc06(device_id: int, register: int, value: int) -> bytes:
        payload = struct.pack(">BBHH", device_id, 0x06, register, value)
        return payload + _crc16(payload)

    async def _transact(self, frame: bytes, expected_len: int) -> bytes:
        assert self._reader is not None and self._writer is not None
        try:
            stale = await asyncio.wait_for(self._reader.read(256), timeout=0.01)
            if stale:
                _LOGGER.debug("Flushed %d stale bytes", len(stale))
        except asyncio.TimeoutError:
            pass

        self._writer.write(frame)
        await self._writer.drain()
        await asyncio.sleep(_INTER_FRAME_DELAY)

        try:
            response = await asyncio.wait_for(
                self._reader.read(expected_len + 4),
                timeout=_READ_TIMEOUT,
            )
        except asyncio.TimeoutError as err:
            raise ModbusClientError("Response timeout") from err

        if not response:
            raise ModbusClientError("Empty response")
        if len(response) >= 2 and response[1] & 0x80:
            exc_code = response[2] if len(response) > 2 else "?"
            raise ModbusClientError(f"Modbus exception 0x{exc_code:02X}")
        if not _check_crc(response):
            raise ModbusClientError(f"CRC error: {response.hex()}")
        return response

    async def read_register(self, device_id: int, register: int) -> int | None:
        async with self._lock:
            try:
                await self.ensure_connected()
                frame    = self._build_fc03(device_id, register)
                response = await self._transact(frame, expected_len=7)
                if response[1] != 0x03 or response[2] < 2:
                    raise ModbusClientError(f"Unexpected FC03 response: {response.hex()}")
                return (response[3] << 8) | response[4]
            except ModbusClientError as err:
                _LOGGER.debug("read_register 0x%04X failed: %s", register, err)
                self._connected = False
                return None

    async def read_registers(self, device_id: int, register: int, count: int) -> list[int | None]:
        async with self._lock:
            try:
                await self.ensure_connected()
                frame    = self._build_fc03(device_id, register, count)
                response = await self._transact(frame, expected_len=3 + count * 2)
                if response[1] != 0x03:
                    raise ModbusClientError(f"Unexpected FC03 response: {response.hex()}")
                byte_count = response[2]
                return [(response[3 + i*2] << 8) | response[4 + i*2] for i in range(byte_count // 2)]
            except ModbusClientError as err:
                _LOGGER.debug("read_registers 0x%04X×%d failed: %s", register, count, err)
                self._connected = False
                return [None] * count

    async def write_register(self, device_id: int, register: int, value: int) -> bool:
        async with self._lock:
            try:
                await self.ensure_connected()
                frame    = self._build_fc06(device_id, register, value)
                response = await self._transact(frame, expected_len=8)
                if response[:6] != frame[:6]:
                    raise ModbusClientError(f"FC06 echo mismatch")
                _LOGGER.debug("write_register 0x%04X = %d OK", register, value)
                return True
            except ModbusClientError as err:
                _LOGGER.debug("write_register 0x%04X failed: %s", register, err)
                self._connected = False
                return False

    async def __aenter__(self) -> "ModbusTCPClient":
        await self.connect()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.disconnect()
