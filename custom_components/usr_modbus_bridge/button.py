"""Button platform — Restart connection."""
from __future__ import annotations
from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import COORDINATOR, DOMAIN
from .coordinator import ModbusBridgeCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id][COORDINATOR]
    async_add_entities([ModbusRestartButton(coordinator, entry)])


class ModbusRestartButton(CoordinatorEntity[ModbusBridgeCoordinator], ButtonEntity):
    _attr_has_entity_name = True
    _attr_name            = "Restart connection"
    _attr_icon            = "mdi:restart"

    def __init__(self, coordinator: ModbusBridgeCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id   = f"{entry.entry_id}_restart"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=coordinator.device.name,
            manufacturer="Madimack" if "inverflow" in coordinator.device.DEVICE_KEY else "Unknown",
            model=coordinator.device.DEVICE_NAME,
            configuration_url=f"http://{entry.data[CONF_HOST]}",
        )

    async def async_press(self) -> None:
        await self.coordinator.async_restart()
