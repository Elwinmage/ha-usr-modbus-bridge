"""
Madimack InverFlow Eco — Modbus device profile.

Register map (confirmed 2026-05-08):
  READ (FC=03):
    0x07D1  rpm_raw       always 0 — wake-up register, not useful as sensor
    0x07D2  on_off        1=running 0=stopped
    0x07D3  speed_pct     actual speed %
    0x07D4  power_w       instant power W (confirmed vs Tuya DPS 5)
    0x07D7  unk_2007      stable value ~322 — unit/meaning unknown
    0x07D8  unk_2008      stable value ~20  — temp sensor? unit unclear (°C? x10?)
    0x07D9  unk_2009      stable value ~28  — NOT confirmed as energy/day
  WRITE (FC=06):
    0x0BB9  setpoint_pct  0=stop, 1-100=speed %

Wake-up:
  A single FC=03 read on 0x07D1 re-activates the RS-485 interface after
  power loss or extended silence. Sent automatically at startup and reconnect.
"""
from __future__ import annotations
import logging
from typing import Any
from .base import ModbusDevice, RegisterDef

_LOGGER = logging.getLogger(__name__)

_REG_SETPOINT = 0x0BB9


class InverFlowEco(ModbusDevice):
    DEVICE_KEY       = "inverflow_eco"
    DEVICE_NAME      = "Madimack InverFlow Eco"
    MODBUS_ADDRESS   = 0xAA
    WAKE_UP_REGISTER = 0x07D1  # single read wakes the RS-485 interface

    READ_REGISTERS = [
        # Wake-up register — read first, value always 0, not exposed as sensor
        RegisterDef(0x07D1, "rpm_raw",   "RPM raw",       "",  1, 0),
        # Confirmed registers
        RegisterDef(0x07D2, "on_off",    "Running",       "",  1, 0),
        RegisterDef(0x07D3, "speed_pct", "Speed",         "%", 1, 0),
        RegisterDef(0x07D4, "power_w",   "Power",         "W", 1, 0),
        # Unknown — stable values, meaning and unit not yet confirmed
        RegisterDef(0x07D7, "unk_2007",  "Unknown 2007",  "",  1, 0),
        RegisterDef(0x07D8, "unk_2008",  "Unknown 2008",  "",  1, 0),
        RegisterDef(0x07D9, "unk_2009",  "Unknown 2009",  "",  1, 0),
    ]

    def __init__(self, name: str = "InverFlow Eco") -> None:
        self._name       = name
        self._last_speed = 80

    async def set_speed(self, client: Any, speed_pct: int) -> bool:
        speed_pct = max(0, min(100, int(speed_pct)))
        ok = await client.write_register(self.MODBUS_ADDRESS, _REG_SETPOINT, speed_pct)
        if ok and speed_pct > 0:
            self._last_speed = speed_pct
        return ok

    async def turn_on(self, client: Any, last_speed: int | None = None) -> bool:
        return await self.set_speed(client, last_speed or self._last_speed)

    async def turn_off(self, client: Any) -> bool:
        return await self.set_speed(client, 0)

    @property
    def sensor_keys(self) -> list[str]:
        # Only expose confirmed sensors — unknowns kept as diagnostic
        return ["speed_pct", "power_w", "unk_2007", "unk_2008", "unk_2009"]

    @property
    def diagnostic_keys(self) -> list[str]:
        """Keys exposed as diagnostic sensors (hidden by default in HA)."""
        return ["unk_2007", "unk_2008", "unk_2009"]

    @property
    def switch_key(self) -> str: return "on_off"

    @property
    def last_speed(self) -> int: return self._last_speed

    @property
    def name(self) -> str: return self._name


SENSOR_DESCRIPTIONS: dict[str, dict] = {
    # Confirmed
    "speed_pct": {
        "name":        "Speed",
        "native_unit": "%",
        "icon":        "mdi:pump",
        "state_class": "measurement",
        "device_class": None,
        "diagnostic":  False,
    },
    "power_w": {
        "name":        "Power",
        "native_unit": "W",
        "icon":        "mdi:lightning-bolt",
        "state_class": "measurement",
        "device_class": "power",
        "diagnostic":  False,
    },
    # Unknown — exposed as diagnostic (hidden by default)
    "unk_2007": {
        "name":        "Unknown reg 2007",
        "native_unit": None,
        "icon":        "mdi:help-circle-outline",
        "state_class": "measurement",
        "device_class": None,
        "diagnostic":  True,
    },
    "unk_2008": {
        "name":        "Unknown reg 2008",
        "native_unit": None,
        "icon":        "mdi:help-circle-outline",
        "state_class": "measurement",
        "device_class": None,
        "diagnostic":  True,
    },
    "unk_2009": {
        "name":        "Unknown reg 2009",
        "native_unit": None,
        "icon":        "mdi:help-circle-outline",
        "state_class": "measurement",
        "device_class": None,
        "diagnostic":  True,
    },
}
