"""USR Modbus Bridge — Home Assistant integration."""
from __future__ import annotations
import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from .bridge.modbus_client import ModbusTCPClient
from .const import (CONF_BAUD, CONF_DEVICE_ADDRESS, CONF_DEVICE_KEY,
                    CONF_SCAN_INTERVAL, COORDINATOR, DEFAULT_SCAN_INTERVAL,
                    DEVICE_PROFILES, DOMAIN)
from .coordinator import ModbusBridgeCoordinator

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SWITCH, Platform.SENSOR, Platform.NUMBER, Platform.BUTTON]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    cfg = {**entry.data, **entry.options}
    profile_cls = DEVICE_PROFILES[cfg[CONF_DEVICE_KEY]]
    device      = profile_cls(name=cfg[CONF_NAME])
    device.MODBUS_ADDRESS = cfg[CONF_DEVICE_ADDRESS]
    client = ModbusTCPClient(host=cfg[CONF_HOST], port=cfg[CONF_PORT], baud=cfg[CONF_BAUD])
    await client.connect()
    coordinator = ModbusBridgeCoordinator(
        hass, client, device, entry.entry_id,
        scan_interval=cfg.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
    )
    await coordinator.async_config_entry_first_refresh()
    hass.data[DOMAIN][entry.entry_id] = {COORDINATOR: coordinator}
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        data = hass.data[DOMAIN].pop(entry.entry_id)
        await data[COORDINATOR].client.disconnect()
    return ok
