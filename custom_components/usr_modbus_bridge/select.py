"""Select platform — one SelectEntity per key in SELECT_DESCRIPTIONS."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.device_registry import DeviceInfo

from .bridge.devices.emec_wdphrh import SELECT_DESCRIPTIONS
from .bridge.emec_runtime import EmecBridgeCoordinator
from .const import COORDINATOR, DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id][COORDINATOR]
    if not isinstance(coordinator, EmecBridgeCoordinator):
        return
    entities = [EmecSelect(coordinator, entry, key) for key in SELECT_DESCRIPTIONS]
    async_add_entities(entities)


class EmecSelect(CoordinatorEntity[EmecBridgeCoordinator], SelectEntity):
    """Enum-like writable field backed by an EMEC read command + write field."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: EmecBridgeCoordinator, entry: ConfigEntry, key: str) -> None:
        super().__init__(coordinator)
        desc = SELECT_DESCRIPTIONS[key]
        self._key      = key
        self._read_cmd = desc["read_cmd"]
        self._field    = desc["field"]
        self._options  = desc["options"]                 # {label: on-wire value}
        self._reverse  = {v: k for k, v in self._options.items()}

        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_name      = desc["name"]
        self._attr_icon      = desc.get("icon")
        self._attr_options   = list(self._options.keys())

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=coordinator.device.name or coordinator.device.DEVICE_NAME,
            manufacturer=coordinator.device.DEVICE_MANUFACTURER,
            model=coordinator.device.DEVICE_NAME,
        )

    @property
    def current_option(self) -> str | None:
        v = self.coordinator.get_value(self._field)
        if v is None:
            return None
        # Options values may be int or str depending on descriptor
        for label, wire in self._options.items():
            if str(wire) == str(v):
                return label
        return None

    @property
    def available(self) -> bool:
        return self.coordinator.available

    async def async_select_option(self, option: str) -> None:
        if option not in self._options:
            return
        ok = await self.coordinator.device.write_field(
            self.coordinator.client, self._read_cmd, self._field,
            self._options[option],
        )
        if not ok:
            from homeassistant.exceptions import HomeAssistantError
            raise HomeAssistantError(f"EMEC {self._key} write did not ACK.")
        await self.coordinator.async_request_refresh()
