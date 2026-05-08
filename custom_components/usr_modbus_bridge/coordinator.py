"""DataUpdateCoordinator for usr_modbus_bridge."""
from __future__ import annotations
import logging
from datetime import timedelta
from typing import Any
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from .bridge.modbus_client import ModbusTCPClient, ModbusClientError
from .bridge.devices.base import DeviceData, ModbusDevice

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=10)


class ModbusBridgeCoordinator(DataUpdateCoordinator[DeviceData]):
    def __init__(self, hass: HomeAssistant, client: ModbusTCPClient,
                 device: ModbusDevice, entry_id: str) -> None:
        self.client   = client
        self.device   = device
        self.entry_id = entry_id
        super().__init__(hass, _LOGGER,
                         name=f"usr_modbus_bridge_{entry_id}",
                         update_interval=SCAN_INTERVAL)

    async def _async_update_data(self) -> DeviceData:
        try:
            data = await self.device.poll(self.client)
        except ModbusClientError as err:
            raise UpdateFailed(f"Modbus poll failed: {err}") from err
        except Exception as err:
            raise UpdateFailed(str(err)) from err
        if not data.online:
            _LOGGER.warning("%s: all registers ERR", self.device.DEVICE_NAME)
        return data

    async def async_set_speed(self, speed_pct: int) -> None:
        await self.device.set_speed(self.client, speed_pct)
        await self.async_request_refresh()

    async def async_turn_on(self) -> None:
        await self.device.turn_on(self.client)
        await self.async_request_refresh()

    async def async_turn_off(self) -> None:
        await self.device.turn_off(self.client)
        await self.async_request_refresh()

    def get_value(self, key: str) -> Any:
        return self.data.values.get(key) if self.data else None

    def get_raw(self, key: str) -> int | None:
        return self.data.raw.get(key) if self.data else None

    @property
    def available(self) -> bool:
        return self.data is not None and self.data.online
