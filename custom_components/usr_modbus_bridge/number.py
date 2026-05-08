"""Number platform — writable speed setpoint."""
from __future__ import annotations
from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import COORDINATOR, DOMAIN
from .coordinator import ModbusBridgeCoordinator
from .switch import _device_info


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id][COORDINATOR]
    async_add_entities([ModbusSpeedNumber(coordinator, entry)])


class ModbusSpeedNumber(CoordinatorEntity[ModbusBridgeCoordinator], NumberEntity):
    _attr_has_entity_name            = True
    _attr_name                       = "Speed setpoint"
    _attr_icon                       = "mdi:speedometer"
    _attr_native_min_value           = 0
    _attr_native_max_value           = 100
    _attr_native_step                = 1
    _attr_native_unit_of_measurement = "%"
    _attr_mode                       = NumberMode.SLIDER

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id   = f"{entry.entry_id}_setpoint"
        self._attr_device_info = _device_info(coordinator, entry)

    @property
    def native_value(self): return self.coordinator.get_value("speed_pct")

    @property
    def available(self) -> bool: return self.coordinator.available

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_speed(int(value))
