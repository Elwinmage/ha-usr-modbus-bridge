"""Switch platform — ON/OFF via setpoint 0 / last_speed."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import COORDINATOR, DOMAIN
from .coordinator import ModbusBridgeCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: ModbusBridgeCoordinator = hass.data[DOMAIN][entry.entry_id][COORDINATOR]
    async_add_entities([ModbusPumpSwitch(coordinator, entry)])


class ModbusPumpSwitch(CoordinatorEntity[ModbusBridgeCoordinator], SwitchEntity):
    """ON/OFF switch — reads op_condition bit0, writes setpoint 0/last_speed."""

    _attr_has_entity_name = True
    _attr_name = "Power"
    _attr_icon = "mdi:pump"

    def __init__(self, coordinator: ModbusBridgeCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id   = f"{entry.entry_id}_switch"
        self._attr_device_info = _device_info(coordinator, entry)

    @property
    def is_on(self) -> bool | None:
        """Running = op_condition bit 0 set."""
        raw = self.coordinator.get_raw("op_condition")
        if raw is None:
            return None
        return bool(raw & 0x0001)

    @property
    def available(self) -> bool:
        return self.coordinator.available

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_turn_on()

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_turn_off()


def _device_info(coordinator: ModbusBridgeCoordinator, entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=coordinator.device.name,
        manufacturer="Madimack" if "inverflow" in coordinator.device.DEVICE_KEY else "Unknown",
        model=coordinator.device.DEVICE_NAME,
        configuration_url=f"http://{entry.data[CONF_HOST]}",
    )
