"""Sensor platform."""
from __future__ import annotations
from homeassistant.components.sensor import SensorEntity, SensorStateClass, SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .bridge.devices.inverflow import SENSOR_DESCRIPTIONS
from .const import COORDINATOR, DOMAIN
from .coordinator import ModbusBridgeCoordinator
from .switch import _device_info


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id][COORDINATOR]
    async_add_entities([
        ModbusSensor(coordinator, entry, key)
        for key in coordinator.device.sensor_keys
        if key in SENSOR_DESCRIPTIONS
    ])


class ModbusSensor(CoordinatorEntity[ModbusBridgeCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry, key: str) -> None:
        super().__init__(coordinator)
        self._key = key
        desc = SENSOR_DESCRIPTIONS[key]
        self._attr_unique_id                  = f"{entry.entry_id}_{key}"
        self._attr_name                       = desc["name"]
        self._attr_native_unit_of_measurement = desc["native_unit"]
        self._attr_icon                       = desc["icon"]
        self._attr_device_info                = _device_info(coordinator, entry)
        sc = desc.get("state_class")
        self._attr_state_class = (SensorStateClass.MEASUREMENT if sc == "measurement"
                                  else SensorStateClass.TOTAL_INCREASING if sc == "total_increasing"
                                  else None)
        dc = desc.get("device_class")
        self._attr_device_class = (SensorDeviceClass.POWER       if dc == "power"
                                   else SensorDeviceClass.TEMPERATURE if dc == "temperature"
                                   else SensorDeviceClass.ENERGY      if dc == "energy"
                                   else None)

    @property
    def native_value(self): return self.coordinator.get_value(self._key)

    @property
    def available(self) -> bool:
        return self.coordinator.available and self.coordinator.get_value(self._key) is not None
