"""Abstract base class for Modbus device profiles."""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RegisterDef:
    address:  int
    key:      str
    name:     str
    unit:     str   = ""
    scale:    float = 1.0
    decimals: int   = 0


@dataclass
class DeviceData:
    raw:    dict[str, int | None] = field(default_factory=dict)
    values: dict[str, Any]        = field(default_factory=dict)
    online: bool                  = False


class ModbusDevice(ABC):
    DEVICE_KEY:      str = ""
    DEVICE_NAME:     str = ""
    MODBUS_ADDRESS:  int = 0x01
    READ_REGISTERS:  list[RegisterDef] = []

    async def poll(self, client: Any) -> DeviceData:
        data = DeviceData()
        if not self.READ_REGISTERS:
            return data
        groups = _group_contiguous(self.READ_REGISTERS)
        for start_reg, reg_defs in groups:
            if len(reg_defs) == 1:
                raw_values = [await client.read_register(self.MODBUS_ADDRESS, start_reg)]
            else:
                raw_values = await client.read_registers(self.MODBUS_ADDRESS, start_reg, len(reg_defs))
            for reg_def, raw in zip(reg_defs, raw_values):
                data.raw[reg_def.key] = raw
                if raw is not None:
                    data.values[reg_def.key] = round(raw * reg_def.scale, reg_def.decimals)
                    data.online = True
                else:
                    data.values[reg_def.key] = None
        return data

    @abstractmethod
    async def set_speed(self, client: Any, speed_pct: int) -> bool: ...

    async def turn_on(self, client: Any, last_speed: int = 80) -> bool:
        return await self.set_speed(client, last_speed)

    async def turn_off(self, client: Any) -> bool:
        return await self.set_speed(client, 0)

    @property
    def sensor_keys(self) -> list[str]: return []

    @property
    def switch_key(self) -> str: return ""

    @property
    def number_key(self) -> str: return ""


def _group_contiguous(regs: list[RegisterDef]) -> list[tuple[int, list[RegisterDef]]]:
    MAX_GROUP = 9
    sorted_regs = sorted(regs, key=lambda r: r.address)
    groups: list[tuple[int, list[RegisterDef]]] = []
    current_start: int | None = None
    current_group: list[RegisterDef] = []
    for reg in sorted_regs:
        if (current_start is None
                or reg.address != current_start + len(current_group)
                or len(current_group) >= MAX_GROUP):
            if current_group:
                groups.append((current_start, current_group))
            current_start = reg.address
            current_group = [reg]
        else:
            current_group.append(reg)
    if current_group:
        groups.append((current_start, current_group))
    return groups
