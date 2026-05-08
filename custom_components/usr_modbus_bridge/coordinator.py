"""DataUpdateCoordinator with auto-reconnect and configurable poll interval."""
from __future__ import annotations
import logging
from datetime import timedelta
from typing import Any
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from .bridge.modbus_client import ModbusTCPClient, ModbusClientError
from .bridge.devices.base import DeviceData, ModbusDevice
from .const import DEFAULT_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)
_MAX_CONSECUTIVE_ERRORS = 3


class ModbusBridgeCoordinator(DataUpdateCoordinator[DeviceData]):
    def __init__(self, hass: HomeAssistant, client: ModbusTCPClient,
                 device: ModbusDevice, entry_id: str,
                 scan_interval: int = DEFAULT_SCAN_INTERVAL) -> None:
        self.client   = client
        self.device   = device
        self.entry_id = entry_id
        self._consecutive_errors = 0
        super().__init__(hass, _LOGGER,
                         name=f"usr_modbus_bridge_{entry_id}",
                         update_interval=timedelta(seconds=scan_interval))

    async def _async_update_data(self) -> DeviceData:
        try:
            data = await self.device.poll(self.client)
        except ModbusClientError as err:
            raise UpdateFailed(f"Modbus poll failed: {err}") from err
        except Exception as err:
            raise UpdateFailed(str(err)) from err

        if not data.online:
            self._consecutive_errors += 1
            _LOGGER.warning("%s: all ERR (%d/%d)", self.device.DEVICE_NAME,
                            self._consecutive_errors, _MAX_CONSECUTIVE_ERRORS)
            if self._consecutive_errors >= _MAX_CONSECUTIVE_ERRORS:
                await self._reconnect()
        else:
            self._consecutive_errors = 0
        return data

    async def _reconnect(self) -> None:
        _LOGGER.warning("%s: reconnecting …", self.device.DEVICE_NAME)
        try:
            await self.client.disconnect()
        except Exception:
            pass
        try:
            await self.client.connect()
            self._consecutive_errors = 0
            _LOGGER.info("%s: reconnected", self.device.DEVICE_NAME)
        except ModbusClientError as err:
            _LOGGER.error("%s: reconnect failed: %s", self.device.DEVICE_NAME, err)

    async def async_restart(self) -> None:
        """Manual restart — called by the button entity."""
        _LOGGER.info("%s: manual restart", self.device.DEVICE_NAME)
        await self._reconnect()
        self._consecutive_errors = 0
        await self.async_request_refresh()

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
