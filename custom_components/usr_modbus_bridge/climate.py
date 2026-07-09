"""Climate platform — Hayward pool heat pump only."""
from __future__ import annotations

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .bridge.devices.hayward import MODE_AUTO, MODE_COOL, MODE_HEAT
from .bridge.hayward_runtime import HaywardCoordinator
from .const import COORDINATOR, DOMAIN

# HA hvac mode <-> pump mode register (1012)
_HVAC_TO_PUMP = {HVACMode.COOL: MODE_COOL, HVACMode.HEAT: MODE_HEAT, HVACMode.AUTO: MODE_AUTO}
_PUMP_TO_HVAC = {MODE_COOL: HVACMode.COOL, MODE_HEAT: HVACMode.HEAT, MODE_AUTO: HVACMode.AUTO}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id][COORDINATOR]
    # Only the Hayward listener coordinator exposes a climate entity.
    if isinstance(coordinator, HaywardCoordinator):
        async_add_entities([HaywardClimate(coordinator, entry)])


class HaywardClimate(CoordinatorEntity[HaywardCoordinator], ClimateEntity):
    _attr_has_entity_name = True
    _enable_turn_on_off_backwards_compatibility = False
    _attr_name = None                       # the device name is the entity name
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 0.5
    _attr_min_temp = 15
    _attr_max_temp = 40
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT, HVACMode.COOL, HVACMode.AUTO]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    def __init__(self, coordinator: HaywardCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_climate"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=coordinator.device_name,
            manufacturer="Hayward",
            model="Pool heat pump",
        )

    # ---- read state ---------------------------------------------------------
    @property
    def available(self) -> bool:
        return self.coordinator.controllable

    @property
    def current_temperature(self) -> float | None:
        return self.coordinator.get_value("current_temp")

    @property
    def target_temperature(self) -> float | None:
        return self.coordinator.get_value("setpoint")

    @property
    def hvac_mode(self) -> HVACMode:
        if not self.coordinator.get_value("power"):
            return HVACMode.OFF
        return _PUMP_TO_HVAC.get(self.coordinator.get_value("mode"), HVACMode.HEAT)

    @property
    def hvac_action(self) -> HVACAction | None:
        if not self.coordinator.get_value("power"):
            return HVACAction.OFF
        fan = self.coordinator.get_value("fan_speed") or 0
        if fan <= 0:
            return HVACAction.IDLE
        mode = self.coordinator.get_value("mode")
        return HVACAction.COOLING if mode == MODE_COOL else HVACAction.HEATING

    # ---- commands -----------------------------------------------------------
    async def async_set_temperature(self, **kwargs) -> None:
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is not None:
            await self.coordinator.async_set_temperature(float(temp))

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self.coordinator.async_set_power(False)
            return
        # ensure powered on, then set the mode
        if not self.coordinator.get_value("power"):
            await self.coordinator.async_set_power(True)
        if hvac_mode in _HVAC_TO_PUMP:
            await self.coordinator.async_set_mode(_HVAC_TO_PUMP[hvac_mode])

    async def async_turn_on(self) -> None:
        await self.coordinator.async_set_power(True)

    async def async_turn_off(self) -> None:
        await self.coordinator.async_set_power(False)
