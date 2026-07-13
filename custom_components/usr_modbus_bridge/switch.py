"""Switch platform — Modbus pump power + EMEC DI contact-type toggles."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .bridge.devices.emec_wdphrh import SWITCH_DESCRIPTIONS
from .bridge.emec_runtime import EmecBridgeCoordinator
from .bridge.hayward_runtime import HaywardCoordinator
from .const import COORDINATOR, DOMAIN
from .coordinator import ModbusBridgeCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id][COORDINATOR]

    if isinstance(coordinator, HaywardCoordinator):
        return

    if isinstance(coordinator, EmecBridgeCoordinator):
        entities = [EmecBooleanSwitch(coordinator, entry, key) for key in SWITCH_DESCRIPTIONS]
        async_add_entities(entities)
        return

    # Modbus polled pumps: pump power switch
    async_add_entities([ModbusPumpSwitch(coordinator, entry)])


class ModbusPumpSwitch(CoordinatorEntity[ModbusBridgeCoordinator], SwitchEntity):
    _attr_has_entity_name = True
    _attr_name = "Power"
    _attr_icon = "mdi:pump"

    def __init__(self, coordinator: ModbusBridgeCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id   = f"{entry.entry_id}_switch"
        self._attr_device_info = _device_info(coordinator, entry)

    @property
    def is_on(self) -> bool | None:
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


class EmecBooleanSwitch(CoordinatorEntity[EmecBridgeCoordinator], SwitchEntity):
    """Diagnostic switch: writes a single 0/1 field via write_field()."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: EmecBridgeCoordinator, entry: ConfigEntry, key: str) -> None:
        super().__init__(coordinator)
        desc = SWITCH_DESCRIPTIONS[key]
        self._key      = key
        self._read_cmd = desc["read_cmd"]
        self._field    = desc["field"]

        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_name      = desc["name"]
        self._attr_icon      = desc.get("icon")

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=coordinator.device.name or coordinator.device.DEVICE_NAME,
            manufacturer=coordinator.device.DEVICE_MANUFACTURER,
            model=coordinator.device.DEVICE_NAME,
        )

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.get_value(self._field)

    @property
    def available(self) -> bool:
        return self.coordinator.available

    async def async_turn_on(self, **kwargs) -> None:
        await self._write(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._write(False)

    async def _write(self, value: bool) -> None:
        ok = await self.coordinator.device.write_field(
            self.coordinator.client, self._read_cmd, self._field, value
        )
        if not ok:
            from homeassistant.exceptions import HomeAssistantError
            raise HomeAssistantError(f"EMEC {self._key} write did not ACK.")
        await self.coordinator.async_request_refresh()


def _device_info(coordinator, entry: ConfigEntry) -> DeviceInfo:
    """Build DeviceInfo for Modbus polled devices."""
    dev_key = getattr(coordinator.device, "DEVICE_KEY", "")
    if "inverflow" in dev_key:
        manufacturer = "Madimack"
    elif "emec" in dev_key:
        manufacturer = "EMEC"
    else:
        manufacturer = "Unknown"
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=coordinator.device.name,
        manufacturer=manufacturer,
        model=coordinator.device.DEVICE_NAME,
        configuration_url=f"http://{entry.data[CONF_HOST]}",
    )
