"""Binary sensor platform — EMEC alarms, dosing activity, outputs, digital inputs."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass, BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.device_registry import DeviceInfo

from .bridge.devices.emec_wdphrh import BINARY_SENSOR_DESCRIPTIONS
from .bridge.emec_runtime import EmecBridgeCoordinator
from .const import COORDINATOR, DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id][COORDINATOR]

    if not isinstance(coordinator, EmecBridgeCoordinator):
        return  # only EMEC uses this platform for now

    entities = [
        EmecBinarySensor(coordinator, entry, key)
        for key in BINARY_SENSOR_DESCRIPTIONS
    ]
    async_add_entities(entities)


class EmecBinarySensor(CoordinatorEntity[EmecBridgeCoordinator], BinarySensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: EmecBridgeCoordinator, entry: ConfigEntry, key: str) -> None:
        super().__init__(coordinator)
        self._key = key
        desc = BINARY_SENSOR_DESCRIPTIONS[key]

        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_name      = desc["name"]
        self._attr_icon      = desc.get("icon")

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=coordinator.device.name or coordinator.device.DEVICE_NAME,
            manufacturer=coordinator.device.DEVICE_MANUFACTURER,
            model=coordinator.device.DEVICE_NAME,
        )

        if desc.get("diagnostic"):
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

        dc = desc.get("device_class")
        self._attr_device_class = (
            BinarySensorDeviceClass.PROBLEM  if dc == "problem"  else
            BinarySensorDeviceClass.RUNNING  if dc == "running"  else
            None
        )

    @property
    def is_on(self) -> bool | None:
        v = self.coordinator.get_value(self._key)
        return bool(v) if v is not None else None

    @property
    def available(self) -> bool:
        return self.coordinator.available and self.coordinator.get_value(self._key) is not None
