"""USR Modbus Bridge — Home Assistant integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT, Platform
from homeassistant.core import HomeAssistant

from .bridge.emec_client import EmecClient
from .bridge.emec_runtime import EmecBridgeCoordinator
from .bridge.hayward_runtime import HaywardCoordinator, HaywardListener
from .bridge.modbus_client import ModbusTCPClient
from .const import (CONF_BAUD, CONF_DEVICE_ADDRESS, CONF_DEVICE_KEY,
                    CONF_REPLY_DELAY, CONF_SCAN_INTERVAL, COORDINATOR,
                    DEFAULT_REPLY_DELAY, DEFAULT_SCAN_INTERVAL, DEVICE_PROFILES,
                    DOMAIN, LISTENER, PLATFORMS_KEY)
from .coordinator import ModbusBridgeCoordinator

_LOGGER = logging.getLogger(__name__)

POLLER_PLATFORMS   = [Platform.SWITCH, Platform.SENSOR, Platform.NUMBER, Platform.BUTTON]
LISTENER_PLATFORMS = [Platform.SENSOR, Platform.CLIMATE]
EMEC_PLATFORMS     = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SWITCH,
    Platform.BUTTON,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    cfg = {**entry.data, **entry.options}
    profile_cls = DEVICE_PROFILES[cfg[CONF_DEVICE_KEY]]

    mode = getattr(profile_cls, "CONNECTION_MODE", "poller")
    if mode == "listener":
        return await _setup_listener(hass, entry, cfg, profile_cls)
    if mode == "emec_poller":
        return await _setup_emec_poller(hass, entry, cfg, profile_cls)
    return await _setup_poller(hass, entry, cfg, profile_cls)


async def _setup_poller(hass, entry, cfg, profile_cls) -> bool:
    device = profile_cls(name=cfg[CONF_NAME])
    device.MODBUS_ADDRESS = cfg[CONF_DEVICE_ADDRESS]

    client = ModbusTCPClient(host=cfg[CONF_HOST], port=cfg[CONF_PORT], baud=cfg[CONF_BAUD])
    await client.connect()

    coordinator = ModbusBridgeCoordinator(
        hass, client, device, entry.entry_id,
        scan_interval=cfg.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
    )
    await coordinator._async_wake_up()
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {COORDINATOR: coordinator, PLATFORMS_KEY: POLLER_PLATFORMS}
    await hass.config_entries.async_forward_entry_setups(entry, POLLER_PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _setup_listener(hass, entry, cfg, profile_cls) -> bool:
    reply_delay_ms = cfg.get(CONF_REPLY_DELAY, DEFAULT_REPLY_DELAY)
    listener = HaywardListener(
        hass, host=cfg[CONF_HOST], port=cfg[CONF_PORT],
        address=cfg[CONF_DEVICE_ADDRESS], reply_delay=reply_delay_ms / 1000.0,
    )
    coordinator = HaywardCoordinator(hass, entry.entry_id, cfg[CONF_NAME], listener)
    listener.start()

    hass.data[DOMAIN][entry.entry_id] = {
        COORDINATOR: coordinator, LISTENER: listener, PLATFORMS_KEY: LISTENER_PLATFORMS,
    }
    await hass.config_entries.async_forward_entry_setups(entry, LISTENER_PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _setup_emec_poller(hass, entry, cfg, profile_cls) -> bool:
    device = profile_cls(name=cfg[CONF_NAME])
    slave_int = int(cfg.get(CONF_DEVICE_ADDRESS, profile_cls.DEFAULT_ADDRESS))
    slave = f"{slave_int:02d}"

    client = EmecClient(
        host=cfg[CONF_HOST],
        port=cfg[CONF_PORT],
        prefix="34",
        slave=slave,
    )
    await client.connect()

    coordinator = EmecBridgeCoordinator(
        hass, client, device, entry.entry_id,
        scan_interval=cfg.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
    )
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {COORDINATOR: coordinator, PLATFORMS_KEY: EMEC_PLATFORMS}
    await hass.config_entries.async_forward_entry_setups(entry, EMEC_PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    data = hass.data[DOMAIN].get(entry.entry_id, {})
    platforms = data.get(PLATFORMS_KEY, POLLER_PLATFORMS)
    ok = await hass.config_entries.async_unload_platforms(entry, platforms)
    if ok:
        data = hass.data[DOMAIN].pop(entry.entry_id)
        if LISTENER in data:
            await data[LISTENER].stop()
        else:
            await data[COORDINATOR].client.disconnect()
    return ok
