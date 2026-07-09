"""
Runtime for the Hayward heat pump: a persistent RS485 listener/responder and
a push-based coordinator.

The control board is the Modbus master, so we cannot poll. HaywardListener
keeps its own TCP connection to the USR gateway, reads the raw stream, drives
the HaywardProtocol engine, and writes replies back with a hold-off (the board
keeps its RS485 driver asserted for a few tens of ms after polling, so an
instant reply gets electrically squashed; the touch panel answers at ~+77 ms).
Whenever the mirrored state changes, it pushes a fresh snapshot to
HaywardCoordinator, which the sensor and climate entities subscribe to.
"""
from __future__ import annotations

import asyncio
import logging
import socket
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .devices.hayward import (
    HAYWARD_SENSORS,
    HAYWARD_SETTING_SENSORS,
    HaywardProtocol,
    REG_MODE,
    REG_POWER,
    REG_SET,
    REG_SETPOINT,
    REG_XSET,
)

_LOGGER = logging.getLogger(__name__)

_READ_TIMEOUT = 0.02       # loop cadence so buffered replies fire promptly
_RECONNECT_DELAY = 3.0
DEFAULT_REPLY_DELAY = 0.06  # hold-off before answering a poll (panel: ~0.077 s)


class HaywardListener:
    """Owns the TCP stream and runs the protocol engine on the event loop."""

    def __init__(self, hass: HomeAssistant, host: str, port: int,
                 address: int, reply_delay: float = DEFAULT_REPLY_DELAY) -> None:
        self._hass = hass
        self._host = host
        self._port = port
        self._reply_delay = reply_delay
        self.proto = HaywardProtocol(address=address)
        self.coordinator: "HaywardCoordinator | None" = None
        self.connected = False
        self._writer: asyncio.StreamWriter | None = None
        self._pending: tuple[float, bytes] | None = None   # (due, frame); latest wins
        self._task: asyncio.Task | None = None
        self._stop = False
        # diagnostics
        self._had_block = {REG_SET: False, REG_XSET: False}
        self._tx_count = 0
        self._connect_time = 0.0
        self._hint_logged = False

    # ---- lifecycle ----------------------------------------------------------
    def start(self) -> None:
        self._task = self._hass.loop.create_task(self._run())

    async def stop(self) -> None:
        self._stop = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        if self._writer:
            try:
                self._writer.close()
            except Exception:
                pass

    # ---- commands (called from HA, i.e. on the loop) ------------------------
    def queue_temp(self, celsius: float) -> bool:
        ok = self.proto.queue_temp(celsius)
        if not ok:
            _LOGGER.warning("Hayward: setpoint not ready (settings block unknown yet)")
        return ok

    def queue_power(self, on: bool) -> bool:
        return self.proto.queue_power(on)

    def queue_mode(self, mode: int) -> bool:
        return self.proto.queue_mode(mode)

    # ---- main loop ----------------------------------------------------------
    async def _run(self) -> None:
        while not self._stop:
            try:
                reader, writer = await asyncio.open_connection(self._host, self._port)
                self._writer = writer
                self.connected = True
                sock = writer.get_extra_info("socket")
                if sock is not None:
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                _LOGGER.info("Hayward: connected to %s:%s", self._host, self._port)
                self._connect_time = self._hass.loop.time()
                self._had_block = {REG_SET: False, REG_XSET: False}
                self._hint_logged = False
                self._publish()

                while not self._stop:
                    try:
                        chunk = await asyncio.wait_for(reader.read(1024), timeout=_READ_TIMEOUT)
                    except asyncio.TimeoutError:
                        chunk = b""
                    if chunk == b"" and reader.at_eof():
                        raise ConnectionError("connection closed by gateway")
                    if chunk:
                        now = self._hass.loop.time()
                        for frame in self.proto.feed(chunk):
                            # latest reply wins, exactly like the validated script:
                            # respond to the most recent request, never emit a
                            # stale frame that would clash with the handshake.
                            self._pending = (now + self._reply_delay, frame)

                    # transmit the pending reply once its hold-off has elapsed
                    if self._pending is not None:
                        now = self._hass.loop.time()
                        if now >= self._pending[0]:
                            frame = self._pending[1]
                            self._pending = None
                            writer.write(frame)
                            self._tx_count += 1
                            if self._tx_count in (1, 10, 50) or self._tx_count % 200 == 0:
                                _LOGGER.debug("Hayward: %d frames transmitted (last %s)",
                                              self._tx_count, frame[:3].hex(" "))
                            await writer.drain()

                    self._log_progress()

                    # reverse-engineering aid: log which settings registers the
                    # board changed (e.g. after a panel action) so we can map
                    # power/mode precisely.
                    if self.proto.block_changes:
                        for block, diffs in self.proto.block_changes:
                            pretty = ", ".join(f"{reg}:{old}->{new}" for reg, old, new in diffs)
                            _LOGGER.info("Hayward: block %d changed -> %s", block, pretty)
                        self.proto.block_changes.clear()

                    # push a fresh snapshot to HA when something changed
                    if self.proto.dirty or self.proto.last_commit is not None:
                        self.proto.dirty = False
                        if self.proto.last_commit is not None:
                            _LOGGER.info("Hayward: command committed %s", self.proto.last_commit)
                            self.proto.last_commit = None
                        self._publish()
            except asyncio.CancelledError:
                break
            except (OSError, ConnectionError, asyncio.TimeoutError) as err:
                _LOGGER.warning("Hayward: connection lost (%s), retrying", err)
            self.connected = False
            self._writer = None
            self._pending = None
            self._publish()
            if not self._stop:
                await asyncio.sleep(_RECONNECT_DELAY)

    # ---- diagnostics --------------------------------------------------------
    def _log_progress(self) -> None:
        for reg, label in ((REG_SET, "1001"), (REG_XSET, "1091")):
            if self.proto.block[reg] is not None and not self._had_block[reg]:
                self._had_block[reg] = True
                _LOGGER.info("Hayward: settings block %s received from board", label)
        if (not self._hint_logged and not self.proto.ready()
                and self._connect_time and self._hass.loop.time() - self._connect_time > 20):
            self._hint_logged = True
            _LOGGER.warning(
                "Hayward: settings blocks not received after 20 s (tx=%d, tmpl=%s, "
                "1001=%s, 1091=%s). If they never arrive, change the setpoint once on "
                "the pump's panel to seed them; if nothing is transmitted at all, check "
                "that no other client (e.g. a standalone script) is answering address "
                "0x%02X on the same gateway.",
                self._tx_count, self.proto.status_tmpl is not None,
                self.proto.block[REG_SET] is not None,
                self.proto.block[REG_XSET] is not None, self.proto.address)

    # ---- state snapshot -----------------------------------------------------
    def _publish(self) -> None:
        p = self.proto
        state: dict[str, Any] = {
            "connected": self.connected,
            "controllable": p.controllable(),
            "climate_ready": p.ready(),
        }
        for key, _label, _unit, _dc, reg, scale in HAYWARD_SENSORS + HAYWARD_SETTING_SENSORS:
            v = p.reg(reg)
            state[key] = round(v * scale, 1) if v is not None else None
        power, mode, sp = p.reg(REG_POWER), p.reg(REG_MODE), p.reg(REG_SETPOINT)
        state["power"] = power
        state["mode"] = mode
        state["setpoint"] = sp / 10 if sp is not None else None
        inlet = p.reg(2046)
        state["current_temp"] = inlet / 10 if inlet is not None else None
        if self.coordinator is not None:
            self.coordinator.async_set_updated_data(state)


class HaywardCoordinator(DataUpdateCoordinator[dict]):
    """Push coordinator: never polls; the listener feeds it snapshots."""

    def __init__(self, hass: HomeAssistant, entry_id: str, name: str,
                 listener: HaywardListener) -> None:
        self.entry_id = entry_id
        self.device_name = name
        self.listener = listener
        listener.coordinator = self
        super().__init__(hass, _LOGGER, name=f"hayward_{entry_id}", update_interval=None)
        self.async_set_updated_data({"connected": False, "climate_ready": False})

    # ---- accessors ----------------------------------------------------------
    def get_value(self, key: str) -> Any:
        return self.data.get(key) if self.data else None

    @property
    def available(self) -> bool:
        return bool(self.data and self.data.get("connected"))

    @property
    def climate_ready(self) -> bool:
        return bool(self.data and self.data.get("climate_ready"))

    @property
    def controllable(self) -> bool:
        return bool(self.data and self.data.get("controllable"))

    # ---- commands -----------------------------------------------------------
    async def async_set_temperature(self, celsius: float) -> None:
        self.listener.queue_temp(celsius)

    async def async_set_power(self, on: bool) -> None:
        self.listener.queue_power(on)

    async def async_set_mode(self, mode: int) -> None:
        self.listener.queue_mode(mode)
