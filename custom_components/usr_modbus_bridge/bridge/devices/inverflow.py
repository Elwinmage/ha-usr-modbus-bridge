"""
Madimack InverFlow Eco — Modbus device profile.

Register map (confirmed 2026-05-08):
  READ  0x07D2  on_off        1=running 0=stopped
        0x07D3  speed_pct     actual speed %
        0x07D4  power_w       instant power W
        0x07D7  energy_total  total energy counter
        0x07D8  temp_c        motor temperature °C
        0x07D9  energy_day    energy today Wh
  WRITE 0x0BB9  setpoint      0=stop, 1-100=speed %
"""
from __future__ import annotations
import logging
from typing import Any
from .base import ModbusDevice, RegisterDef

_LOGGER = logging.getLogger(__name__)
_REG_SETPOINT = 0x0BB9


class InverFlowEco(ModbusDevice):
    DEVICE_KEY     = "inverflow_eco"
    DEVICE_NAME    = "Madimack InverFlow Eco"
    MODBUS_ADDRESS = 0xAA  # 170 — fixed, shown in pump menu

    READ_REGISTERS = [
        RegisterDef(0x07D2, "on_off",       "Running",        "",   1, 0),
        RegisterDef(0x07D3, "speed_pct",    "Speed",          "%",  1, 0),
        RegisterDef(0x07D4, "power_w",      "Power",          "W",  1, 0),
        RegisterDef(0x07D7, "energy_total", "Energy total",   "",   1, 0),
        RegisterDef(0x07D8, "temp_c",       "Temperature",    "°C", 1, 0),
        RegisterDef(0x07D9, "energy_day",   "Energy today",   "Wh", 1, 0),
    ]

    def __init__(self, name: str = "InverFlow Eco") -> None:
        self._name        = name
        self._last_speed  = 80

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
        return ["speed_pct", "power_w", "temp_c", "energy_day", "energy_total"]

    @property
    def switch_key(self) -> str: return "on_off"

    @property
    def last_speed(self) -> int: return self._last_speed

    @property
    def name(self) -> str: return self._name


SENSOR_DESCRIPTIONS: dict[str, dict] = {
    "speed_pct":    {"name": "Speed",           "native_unit": "%",   "icon": "mdi:pump",           "state_class": "measurement",      "device_class": None},
    "power_w":      {"name": "Power",            "native_unit": "W",   "icon": "mdi:lightning-bolt", "state_class": "measurement",      "device_class": "power"},
    "temp_c":       {"name": "Motor temperature","native_unit": "°C",  "icon": "mdi:thermometer",    "state_class": "measurement",      "device_class": "temperature"},
    "energy_day":   {"name": "Energy today",     "native_unit": "Wh",  "icon": "mdi:solar-power",    "state_class": "total_increasing", "device_class": "energy"},
    "energy_total": {"name": "Energy total",     "native_unit": None,  "icon": "mdi:counter",        "state_class": "total_increasing", "device_class": None},
}
