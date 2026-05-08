"""
DataUpdateCoordinator for usr_modbus_bridge.

Resilience features:
  - Wake-up ping (single register read) at startup and after every reconnect
  - Auto-reconnect after N consecutive all-ERR polls
  - Silence timeout: if no valid data received for X minutes -> force reconnect + wake-up
  - Manual restart button triggers the same reconnect + wake-up sequence
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .bridge.modbus_client import ModbusTCPClient, ModbusClientError
from .bridge.devices.base import DeviceData, ModbusDevice
from .const import DEFAULT_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)

_MAX_CONSECUTIVE_ERRORS  = 3
_SILENCE_TIMEOUT_MINUTES = 5


class ModbusBridgeCoordinator(DataUpdateCoordinator[DeviceData]):

    def __init__(self, hass: HomeAssistant, client: ModbusTCPClient,
                 device: ModbusDevice, entry_id: str,
                 scan_interval: int = DEFAULT_SCAN_INTERVAL) -> None:
        self.client   = client
        self.device   = device
        self.entry_id = entry_id
        self._consecutive_errors  = 0
        self._last_valid_data: datetime | None = None
        super().__init__(hass, _LOGGER,
                         name=f"usr_modbus_bridge_{entry_id}",
                         update_interval=timedelta(seconds=scan_interval))

    # ---- Wake-up -------------------------------------------------------------

    async def _async_wake_up(self) -> None:
        """Single register read to wake the device RS-485 interface."""
        wake_reg = getattr(self.device, "WAKE_UP_REGISTER", None)
        if wake_reg is None:
            return
        _LOGGER.info("%s: wake-up ping on reg 0x%04X", self.device.DEVICE_NAME, wake_reg)
        await self.client.read_register(self.device.MODBUS_ADDRESS, wake_reg)
        await asyncio.sleep(0.5)
        _LOGGER.info("%s: wake-up done", self.device.DEVICE_NAME)

    # ---- Reconnect -----------------------------------------------------------

    async def _reconnect(self) -> None:
        """Drop TCP, reconnect, wake-up."""
        _LOGGER.warning("%s: reconnecting ...", self.device.DEVICE_NAME)
        try:
            await self.client.disconnect()
        except Exception:
            pass
        try:
            await self.client.connect()
            self._consecutive_errors = 0
            _LOGGER.info("%s: TCP reconnected", self.device.DEVICE_NAME)
            await self._async_wake_up()
        except ModbusClientError as err:
            _LOGGER.error("%s: reconnect failed: %s", self.device.DEVICE_NAME, err)

    # ---- Poll ----------------------------------------------------------------

    async def _async_update_data(self) -> DeviceData:
        # Silence timeout check
        if self._last_valid_data is not None:
            silence = datetime.now() - self._last_valid_data
            if silence > timedelta(minutes=_SILENCE_TIMEOUT_MINUTES):
                _LOGGER.warning("%s: no valid data for %.0f min, reconnecting",
                                self.device.DEVICE_NAME, silence.total_seconds() / 60)
                await self._reconnect()

        try:
            data = await self.device.poll(self.client)
        except ModbusClientError as err:
            raise UpdateFailed(f"Modbus poll failed: {err}") from err
        except Exception as err:
            _LOGGER.exception("Unexpected poll error")
            raise UpdateFailed(str(err)) from err

        if not data.online:
            self._consecutive_errors += 1
            _LOGGER.warning("%s: all ERR (%d/%d)", self.device.DEVICE_NAME,
                            self._consecutive_errors, _MAX_CONSECUTIVE_ERRORS)
            if self._consecutive_errors >= _MAX_CONSECUTIVE_ERRORS:
                await self._reconnect()
        else:
            self._consecutive_errors = 0
            self._last_valid_data    = datetime.now()

        return data

    # ---- Public restart (button) ---------------------------------------------

    async def async_restart(self) -> None:
        _LOGGER.info("%s: manual restart", self.device.DEVICE_NAME)
        await self._reconnect()
        self._consecutive_errors = 0
        self._last_valid_data    = None
        await self.async_request_refresh()

    # ---- Write helpers -------------------------------------------------------

    async def async_set_speed(self, speed_pct: int) -> None:
        ok = await self.device.set_speed(self.client, speed_pct)
        if not ok:
            _LOGGER.error("set_speed(%d) failed", speed_pct)
        await self.async_request_refresh()

    async def async_turn_on(self) -> None:
        ok = await self.device.turn_on(self.client)
        if not ok:
            _LOGGER.error("turn_on failed")
        await self.async_request_refresh()

    async def async_turn_off(self) -> None:
        ok = await self.device.turn_off(self.client)
        if not ok:
            _LOGGER.error("turn_off failed")
        await self.async_request_refresh()

    # ---- Accessors -----------------------------------------------------------

    def get_value(self, key: str) -> Any:
        return self.data.values.get(key) if self.data else None

    def get_raw(self, key: str) -> int | None:
        return self.data.raw.get(key) if self.data else None

    @property
    def available(self) -> bool:
        return self.data is not None and self.data.online
