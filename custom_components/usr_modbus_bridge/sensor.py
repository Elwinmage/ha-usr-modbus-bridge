"""Sensor platform — numeric + text error sensor."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass, SensorEntity, SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from homeassistant.helpers.device_registry import DeviceInfo
from .bridge.devices.hayward import HAYWARD_SENSORS, HAYWARD_SETTING_SENSORS
from .bridge.devices.inverflow import SENSOR_DESCRIPTIONS, decode_error
from .bridge.hayward_runtime import HaywardCoordinator
from .const import COORDINATOR, DOMAIN
from .coordinator import ModbusBridgeCoordinator
from .switch import _device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id][COORDINATOR]

    # Hayward heat pump: push coordinator with its own sensor set.
    if isinstance(coordinator, HaywardCoordinator):
        ents: list = [HaywardSensor(coordinator, entry, spec) for spec in HAYWARD_SENSORS]
        ents += [HaywardSensor(coordinator, entry, spec, diagnostic=True)
                 for spec in HAYWARD_SETTING_SENSORS]
        async_add_entities(ents)
        return

    entities: list = []

    # Real-time sensors
    all_keys = coordinator.device.sensor_keys + getattr(coordinator.device, "diagnostic_keys", [])
    for key in all_keys:
        if key in SENSOR_DESCRIPTIONS:
            entities.append(ModbusSensor(coordinator, entry, key))

    # Error text sensor (decoded bitmask from register 2001)
    entities.append(ModbusErrorSensor(coordinator, entry))

    async_add_entities(entities)


class ModbusSensor(CoordinatorEntity[ModbusBridgeCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry: ConfigEntry, key: str) -> None:
        super().__init__(coordinator)
        self._key = key
        desc = SENSOR_DESCRIPTIONS[key]

        self._attr_unique_id                  = f"{entry.entry_id}_{key}"
        self._attr_name                       = desc["name"]
        self._attr_native_unit_of_measurement = desc.get("native_unit")
        self._attr_icon                       = desc.get("icon")
        self._attr_device_info                = _device_info(coordinator, entry)

        if desc.get("diagnostic"):
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

        sc = desc.get("state_class")
        self._attr_state_class = (
            SensorStateClass.MEASUREMENT      if sc == "measurement"      else
            SensorStateClass.TOTAL_INCREASING if sc == "total_increasing" else
            None
        )
        dc = desc.get("device_class")
        self._attr_device_class = (
            SensorDeviceClass.POWER       if dc == "power"       else
            SensorDeviceClass.TEMPERATURE if dc == "temperature" else
            SensorDeviceClass.ENERGY      if dc == "energy"      else
            None
        )

    @property
    def native_value(self):
        return self.coordinator.get_value(self._key)

    @property
    def available(self) -> bool:
        return self.coordinator.available and self.coordinator.get_value(self._key) is not None


class ModbusErrorSensor(CoordinatorEntity[ModbusBridgeCoordinator], SensorEntity):
    """Decoded error text from register 2001 bitmask."""

    _attr_has_entity_name = True
    _attr_name            = "Error"
    _attr_icon            = "mdi:alert-circle-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id   = f"{entry.entry_id}_error"
        self._attr_device_info = _device_info(coordinator, entry)

    @property
    def native_value(self) -> str:
        code = self.coordinator.get_raw("error_code")
        return decode_error(code or 0)

    @property
    def available(self) -> bool:
        return self.coordinator.available


class HaywardSensor(CoordinatorEntity[HaywardCoordinator], SensorEntity):
    """Sensor fed by the Hayward listener snapshot."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: HaywardCoordinator, entry: ConfigEntry, spec,
                 diagnostic: bool = False) -> None:
        super().__init__(coordinator)
        key, label, unit, device_class, _reg, _scale = spec
        self._key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_name = label
        self._attr_native_unit_of_measurement = unit
        self._attr_state_class = SensorStateClass.MEASUREMENT
        if diagnostic:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_device_class = (
            SensorDeviceClass.TEMPERATURE if device_class == "temperature" else
            SensorDeviceClass.CURRENT     if device_class == "current"     else
            SensorDeviceClass.VOLTAGE     if device_class == "voltage"     else
            None
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=coordinator.device_name,
            manufacturer="Hayward",
            model="Pool heat pump",
        )

    @property
    def native_value(self):
        return self.coordinator.get_value(self._key)

    @property
    def available(self) -> bool:
        return self.coordinator.available and self.coordinator.get_value(self._key) is not None
