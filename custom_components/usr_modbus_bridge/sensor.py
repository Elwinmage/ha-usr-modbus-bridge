"""Sensor platform for usr_modbus_bridge."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .bridge.devices.inverflow import SENSOR_DESCRIPTIONS
from .const import COORDINATOR, DOMAIN
from .coordinator import ModbusBridgeCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: ModbusBridgeCoordinator = hass.data[DOMAIN][entry.entry_id][COORDINATOR]
    async_add_entities([
        ModbusSensor(coordinator, entry, key)
        for key in coordinator.device.sensor_keys
        if key in SENSOR_DESCRIPTIONS
    ])


class ModbusSensor(CoordinatorEntity[ModbusBridgeCoordinator], SensorEntity):
    """One sensor per key declared in the device profile."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ModbusBridgeCoordinator,
        entry: ConfigEntry,
        key: str,
    ) -> None:
        super().__init__(coordinator)
        self._key = key
        desc = SENSOR_DESCRIPTIONS[key]

        self._attr_unique_id                  = f"{entry.entry_id}_{key}"
        self._attr_name                       = desc["name"]
        self._attr_native_unit_of_measurement = desc.get("native_unit")
        self._attr_icon                       = desc.get("icon")
        self._attr_device_info                = _device_info(coordinator, entry)

        # Diagnostic sensors are hidden by default in HA UI
        if desc.get("diagnostic"):
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

        # State class
        sc = desc.get("state_class")
        self._attr_state_class = (
            SensorStateClass.MEASUREMENT       if sc == "measurement"       else
            SensorStateClass.TOTAL_INCREASING  if sc == "total_increasing"  else
            None
        )

        # Device class
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
        return (
            self.coordinator.available
            and self.coordinator.get_value(self._key) is not None
        )


def _device_info(coordinator: ModbusBridgeCoordinator, entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=coordinator.device.name,
        manufacturer="Madimack" if "inverflow" in coordinator.device.DEVICE_KEY else "Unknown",
        model=coordinator.device.DEVICE_NAME,
        configuration_url=f"http://{entry.data[CONF_HOST]}",
    )
