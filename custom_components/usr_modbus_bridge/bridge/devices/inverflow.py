"""
Madimack InverFlow Eco — Modbus device profile.

Register map (fully confirmed 2026-05-08):

  READ (FC=03):
    0x07D1  2001  error_code    Error bitmask (0=no error) — also wake-up register
    0x07D2  2002  op_condition  Operation condition bitmask (bit0=1 means running)
    0x07D3  2003  speed_pct     Running capacity % (actual speed)
    0x07D4  2004  power_w       Instant power W
    0x07D7  2007  const_2007    Firmware constant (~89) — meaning unknown, do not expose
    0x07D8  2008  const_2008    Firmware constant (~20) — meaning unknown, do not expose
    0x07D9  2009  const_2009    Firmware constant (~28) — meaning unknown, do not expose

  WRITE (FC=06):
    0x0BB9  3001  setpoint_pct  Target speed % — 0=stop, 30-100=run (snapped to 5%)

  Error bitmask (register 2001):
    bit  0  DC voltage abnormal
    bit  1  AC current sampling circuit failure
    bit  2  Phase-deficient protection
    bit  3  Master drive error
    bit  4  Heatsink sensor error
    bit  5  Heatsink overheat
    bit  6  Output current exceeds limit
    bit  7  Input voltage abnormal
    bit  8  No water protection
    bit  9  Panel-master comm failure
    bit 10  Panel EEPROM read error
    bit 11  RTC read error
    bit 12  Main EEPROM read error
    bit 13  Motor current detection error
    bit 14  Motor power overload
    bit 15  PFC protection

  Wake-up:
    Reading 0x07D1 re-activates the RS-485 interface after power loss or
    extended silence. Always read this register first.

  Speed constraints:
    Minimum running speed: 30%
    Step: 5% (pump ignores values not snapped to 5%)
    0 = stop (pump cuts power)
"""
from __future__ import annotations
import logging
from typing import Any
from .base import ModbusDevice, RegisterDef

_LOGGER = logging.getLogger(__name__)

_REG_SETPOINT = 0x0BB9
_SPEED_MIN    = 30
_SPEED_STEP   = 5

ERROR_BITS: list[str] = [
    "DC voltage abnormal",
    "AC current sampling circuit failure",
    "Phase-deficient protection",
    "Master drive error",
    "Heatsink sensor error",
    "Heatsink overheat",
    "Output current exceeds limit",
    "Input voltage abnormal",
    "No water protection",
    "Panel-master comm failure",
    "Panel EEPROM read error",
    "RTC read error",
    "Main EEPROM read error",
    "Motor current detection error",
    "Motor power overload",
    "PFC protection",
]


def decode_error(code: int) -> str:
    if code == 0:
        return "No error"
    return "; ".join(msg for i, msg in enumerate(ERROR_BITS) if code & (1 << i))


def decode_running(op_condition: int) -> bool:
    return bool(op_condition & 0x0001)


def snap_speed(speed_pct: float) -> int:
    """Clamp to 30-100% and snap to nearest 5%."""
    if speed_pct == 0:
        return 0
    v = max(_SPEED_MIN, min(100, speed_pct))
    return max(_SPEED_MIN, min(100, round(v / _SPEED_STEP) * _SPEED_STEP))


class InverFlowEco(ModbusDevice):
    DEVICE_KEY       = "inverflow_eco"
    DEVICE_NAME      = "Madimack InverFlow Eco"
    MODBUS_ADDRESS   = 0xAA
    WAKE_UP_REGISTER = 0x07D1

    READ_REGISTERS = [
        # Wake-up + error bitmask — always read first
        RegisterDef(0x07D1, "error_code",   "Error code",    "",  1, 0),
        # Operation condition bitmask (bit0=running)
        RegisterDef(0x07D2, "op_condition", "Op condition",  "",  1, 0),
        # Useful real-time sensors
        RegisterDef(0x07D3, "speed_pct",    "Speed",         "%", 1, 0),
        RegisterDef(0x07D4, "power_w",      "Power",         "W", 1, 0),
        # Firmware constants — kept for diagnostic only, never change at runtime
        RegisterDef(0x07D7, "const_2007",   "Const 2007",    "",  1, 0),
        RegisterDef(0x07D8, "const_2008",   "Const 2008",    "",  1, 0),
        RegisterDef(0x07D9, "const_2009",   "Const 2009",    "",  1, 0),
    ]

    def __init__(self, name: str = "InverFlow Eco") -> None:
        self._name       = name
        self._last_speed = 80

    async def set_speed(self, client: Any, speed_pct: int) -> bool:
        value = snap_speed(speed_pct)
        ok = await client.write_register(self.MODBUS_ADDRESS, _REG_SETPOINT, value)
        if ok and value > 0:
            self._last_speed = value
        return ok

    async def turn_on(self, client: Any, last_speed: int | None = None) -> bool:
        return await self.set_speed(client, last_speed or self._last_speed)

    async def turn_off(self, client: Any) -> bool:
        return await self.set_speed(client, 0)

    def is_running(self, data: dict) -> bool:
        op = data.get("op_condition")
        return decode_running(op) if op is not None else False

    def error_text(self, data: dict) -> str:
        return decode_error(data.get("error_code") or 0)

    @property
    def sensor_keys(self) -> list[str]:
        # Only confirmed real-time sensors
        return ["speed_pct", "power_w"]

    @property
    def diagnostic_keys(self) -> list[str]:
        # Firmware constants — hidden by default in HA
        return ["const_2007", "const_2008", "const_2009"]

    @property
    def switch_key(self) -> str: return "op_condition"

    @property
    def last_speed(self) -> int: return self._last_speed

    @property
    def name(self) -> str: return self._name


SENSOR_DESCRIPTIONS: dict[str, dict] = {
    # Real-time sensors
    "speed_pct": {
        "name":         "Speed",
        "native_unit":  "%",
        "icon":         "mdi:pump",
        "state_class":  "measurement",
        "device_class": None,
        "diagnostic":   False,
    },
    "power_w": {
        "name":         "Power",
        "native_unit":  "W",
        "icon":         "mdi:lightning-bolt",
        "state_class":  "measurement",
        "device_class": "power",
        "diagnostic":   False,
    },
    # Firmware constants — diagnostic, hidden by default
    "const_2007": {
        "name":         "Firmware const 2007",
        "native_unit":  None,
        "icon":         "mdi:code-brackets",
        "state_class":  "measurement",
        "device_class": None,
        "diagnostic":   True,
    },
    "const_2008": {
        "name":         "Firmware const 2008",
        "native_unit":  None,
        "icon":         "mdi:code-brackets",
        "state_class":  "measurement",
        "device_class": None,
        "diagnostic":   True,
    },
    "const_2009": {
        "name":         "Firmware const 2009",
        "native_unit":  None,
        "icon":         "mdi:code-brackets",
        "state_class":  "measurement",
        "device_class": None,
        "diagnostic":   True,
    },
}
