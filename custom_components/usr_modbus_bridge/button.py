"""Button platform — restart connection, reset alarms, sync clock (EMEC only)."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.device_registry import DeviceInfo

from .bridge.emec_runtime import EmecBridgeCoordinator
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

    if isinstance(coordinator, EmecBridgeCoordinator):
        async_add_entities([
            EmecRestartButton(coordinator, entry),
            EmecResetAlarmsButton(coordinator, entry),
            EmecSyncClockButton(coordinator, entry),
        ])
        return

    if isinstance(coordinator, HaywardCoordinator):
        return  # no restart button in listener mode

    if isinstance(coordinator, ModbusBridgeCoordinator):
        async_add_entities([ModbusRestartButton(coordinator, entry)])


class ModbusRestartButton(CoordinatorEntity[ModbusBridgeCoordinator], ButtonEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "Restart connection"
    _attr_icon = "mdi:restart"

    def __init__(self, coordinator: ModbusBridgeCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id   = f"{entry.entry_id}_restart"
        self._attr_device_info = _device_info(coordinator, entry)

    async def async_press(self) -> None:
        await self.coordinator.async_restart()


def _emec_device_info(coordinator: EmecBridgeCoordinator, entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=coordinator.device.name or coordinator.device.DEVICE_NAME,
        manufacturer=coordinator.device.DEVICE_MANUFACTURER,
        model=coordinator.device.DEVICE_NAME,
    )


class EmecRestartButton(CoordinatorEntity[EmecBridgeCoordinator], ButtonEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "Restart connection"
    _attr_icon = "mdi:restart"

    def __init__(self, coordinator: EmecBridgeCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id   = f"{entry.entry_id}_restart"
        self._attr_device_info = _emec_device_info(coordinator, entry)

    async def async_press(self) -> None:
        await self.coordinator.async_restart()


class EmecResetAlarmsButton(CoordinatorEntity[EmecBridgeCoordinator], ButtonEntity):
    _attr_has_entity_name = True
    _attr_name = "Reset alarms"
    _attr_icon = "mdi:alarm-off"

    def __init__(self, coordinator: EmecBridgeCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id   = f"{entry.entry_id}_reset_alarms"
        self._attr_device_info = _emec_device_info(coordinator, entry)

    async def async_press(self) -> None:
        ok = await self.coordinator.device.reset_all_alarms(self.coordinator.client)
        if ok:
            await self.coordinator.async_request_refresh()
        else:
            from homeassistant.exceptions import HomeAssistantError
            raise HomeAssistantError("EMEC reset alarms did not ACK.")


class EmecSyncClockButton(CoordinatorEntity[EmecBridgeCoordinator], ButtonEntity):
    """Push HA's current wall-clock time to the pump via clockw."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_name = "Sync clock to HA"
    _attr_icon = "mdi:clock-check"

    def __init__(self, coordinator: EmecBridgeCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id   = f"{entry.entry_id}_sync_clock"
        self._attr_device_info = _emec_device_info(coordinator, entry)

    async def async_press(self) -> None:
        ok = await self.coordinator.device.sync_clock(self.coordinator.client)
        if not ok:
            from homeassistant.exceptions import HomeAssistantError
            raise HomeAssistantError("EMEC clock sync did not ACK.")
        await self.coordinator.async_request_refresh()
