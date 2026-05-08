"""USR Modbus Bridge integration."""
from __future__ import annotations
import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from .bridge.modbus_client import ModbusTCPClient
from .const import CONF_BAUD, CONF_DEVICE_ADDRESS, CONF_DEVICE_KEY, COORDINATOR, DEVICE_PROFILES, DOMAIN
from .coordinator import ModbusBridgeCoordinator

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SWITCH, Platform.SENSOR, Platform.NUMBER]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    profile_cls = DEVICE_PROFILES[entry.data[CONF_DEVICE_KEY]]
    device      = profile_cls(name=entry.data[CONF_NAME])
    device.MODBUS_ADDRESS = entry.data[CONF_DEVICE_ADDRESS]
    client = ModbusTCPClient(host=entry.data[CONF_HOST],
                             port=entry.data[CONF_PORT],
                             baud=entry.data[CONF_BAUD])
    await client.connect()
    coordinator = ModbusBridgeCoordinator(hass, client, device, entry.entry_id)
    await coordinator.async_config_entry_first_refresh()
    hass.data[DOMAIN][entry.entry_id] = {COORDINATOR: coordinator}
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        data = hass.data[DOMAIN].pop(entry.entry_id)
        await data[COORDINATOR].client.disconnect()
    return ok
