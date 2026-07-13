"""
EMEC Bridge Coordinator.

Mirrors ModbusBridgeCoordinator but wraps an EmecClient. The EMEC session is
kept alive by a background heartbeat inside the client, so all this
coordinator has to do is fire a poll every scan_interval, track offline
status, and reconnect on prolonged silence.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .devices.base import DeviceData
from .devices.emec_wdphrh import EmecWdphrh
from .emec_client import EmecClient, EmecClientError

_LOGGER = logging.getLogger(__name__)

_MAX_CONSECUTIVE_ERRORS = 3
_SILENCE_TIMEOUT_MINUTES = 5


class EmecBridgeCoordinator(DataUpdateCoordinator[DeviceData]):
    """Polls the EMEC WDPHRH controller through EmecClient."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: EmecClient,
        device: EmecWdphrh,
        entry_id: str,
        scan_interval: int = 10,
    ) -> None:
        self.client = client
        self.device = device
        self.entry_id = entry_id
        self._consecutive_errors = 0
        self._last_valid_data: datetime | None = None
        super().__init__(
            hass, _LOGGER,
            name=f"emec_bridge_{entry_id}",
            update_interval=timedelta(seconds=scan_interval),
        )

    async def _reconnect(self) -> None:
        _LOGGER.warning("EMEC: reconnecting...")
        try:
            await self.client.disconnect()
        except Exception:
            pass
        try:
            await self.client.connect()
            self._consecutive_errors = 0
            _LOGGER.info("EMEC: reconnected")
        except EmecClientError as err:
            _LOGGER.error("EMEC reconnect failed: %s", err)

    async def _async_update_data(self) -> DeviceData:
        # Silence timeout check
        if self._last_valid_data is not None:
            silence = datetime.now() - self._last_valid_data
            if silence > timedelta(minutes=_SILENCE_TIMEOUT_MINUTES):
                _LOGGER.warning(
                    "EMEC: no valid data for %.0f min, reconnecting",
                    silence.total_seconds() / 60,
                )
                await self._reconnect()

        try:
            data = await self.device.poll(self.client)
        except EmecClientError as err:
            raise UpdateFailed(f"EMEC poll failed: {err}") from err
        except Exception as err:
            _LOGGER.exception("Unexpected EMEC poll error")
            raise UpdateFailed(str(err)) from err

        if not data.online:
            self._consecutive_errors += 1
            _LOGGER.warning(
                "EMEC: no data (%d/%d)",
                self._consecutive_errors,
                _MAX_CONSECUTIVE_ERRORS,
            )
            if self._consecutive_errors >= _MAX_CONSECUTIVE_ERRORS:
                await self._reconnect()
        else:
            self._consecutive_errors = 0
            self._last_valid_data = datetime.now()

        return data

    async def async_restart(self) -> None:
        _LOGGER.info("EMEC: manual restart")
        await self._reconnect()
        self._consecutive_errors = 0
        self._last_valid_data = None
        await self.async_request_refresh()

    def get_value(self, key: str) -> Any:
        return self.data.values.get(key) if self.data else None

    def get_raw(self, key: str) -> str | None:
        return self.data.raw.get(key) if self.data else None

    @property
    def available(self) -> bool:
        return self.data is not None and self.data.online
