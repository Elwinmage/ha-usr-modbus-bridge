"""Number platform — Modbus setpoint numbers plus EMEC writable numbers."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.components.number.const import NumberDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.device_registry import DeviceInfo

from .bridge.devices.emec_wdphrh import NUMBER_DESCRIPTIONS as EMEC_NUMBERS
from .bridge.emec_runtime import EmecBridgeCoordinator
from .const import COORDINATOR, DOMAIN
from .coordinator import ModbusBridgeCoordinator
from .switch import _device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id][COORDINATOR]

    # EMEC controller: expose one NumberEntity per writable field.
    if isinstance(coordinator, EmecBridgeCoordinator):
        entities = [
            EmecNumber(coordinator, entry, key) for key in EMEC_NUMBERS
        ]
        async_add_entities(entities)
        return

    # Modbus polled pumps: single speed setpoint number.
    if not isinstance(coordinator, ModbusBridgeCoordinator):
        return
    async_add_entities([ModbusSpeedNumber(coordinator, entry)])


# ---- Modbus speed setpoint (unchanged from previous integration) ------------

class ModbusSpeedNumber(CoordinatorEntity[ModbusBridgeCoordinator], NumberEntity):
    """Speed setpoint slider for pumps (0 / 30-100 %, step 5)."""

    _attr_has_entity_name = True
    _attr_name = "Speed setpoint"
    _attr_icon = "mdi:speedometer"
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 5
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator: ModbusBridgeCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id   = f"{entry.entry_id}_speed_setpoint"
        self._attr_device_info = _device_info(coordinator, entry)

    @property
    def native_value(self) -> float | None:
        v = self.coordinator.get_value("speed_pct")
        return float(v) if v is not None else None

    @property
    def available(self) -> bool:
        return self.coordinator.available

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_speed(int(value))


# ---- EMEC number entities ---------------------------------------------------

class EmecNumber(CoordinatorEntity[EmecBridgeCoordinator], NumberEntity):
    """Writable number entity backed by an EMEC field."""

    _attr_has_entity_name = True
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: EmecBridgeCoordinator, entry: ConfigEntry,
                 key: str) -> None:
        super().__init__(coordinator)
        desc = EMEC_NUMBERS[key]
        self._key      = key
        self._read_cmd = desc["read_cmd"]
        self._field    = desc["field"]

        self._attr_unique_id                  = f"{entry.entry_id}_{key}"
        self._attr_name                       = desc["name"]
        self._attr_icon                       = desc.get("icon")
        self._attr_native_unit_of_measurement = desc.get("unit")
        self._attr_native_min_value           = desc["min_value"]
        self._attr_native_max_value           = desc["max_value"]
        self._attr_native_step                = desc["step"]

        dc = desc.get("device_class")
        if dc == "ph":
            self._attr_device_class = NumberDeviceClass.PH
        elif dc == "voltage":
            self._attr_device_class = NumberDeviceClass.VOLTAGE

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=coordinator.device.name or coordinator.device.DEVICE_NAME,
            manufacturer=coordinator.device.DEVICE_MANUFACTURER,
            model=coordinator.device.DEVICE_NAME,
        )

    @property
    def native_value(self) -> float | None:
        v = self.coordinator.get_value(self._field)
        return float(v) if v is not None else None

    @property
    def available(self) -> bool:
        return self.coordinator.available

    async def async_set_native_value(self, value: float) -> None:
        """Write the new value to the pump and refresh the state."""
        ok = await self.coordinator.device.write_field(
            self.coordinator.client, self._read_cmd, self._field, value
        )
        if not ok:
            # Surface the failure to the UI without crashing the entity
            from homeassistant.exceptions import HomeAssistantError
            raise HomeAssistantError(
                f"EMEC write of {self._field} failed (pump did not ACK)."
            )
        await self.coordinator.async_request_refresh()
