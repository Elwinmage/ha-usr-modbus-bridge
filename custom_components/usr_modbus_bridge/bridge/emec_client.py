"""
EMEC WDPHRH ERMES-family ASCII protocol client.

Sits alongside ModbusTCPClient. Speaks the reverse-engineered protocol:
    Master heartbeat : "34tb00 #0#\\r\\n"   every ~500 ms (keeps session alive)
    Master query     : "3401<cmd>\\r\\r"    (double CR terminator)
    Pump reply       : "34gpd01&WD#...#<cmd>end\\r"       (read response)
                       "34gpd01&<cmd>okend\\r"            (write ACK)

A background heartbeat task keeps the pump talking. A background reader task
fills a shared RX buffer. Queries send a request, then poll the buffer for
the expected reply.

Thread-safety: an asyncio.Lock serialises writes.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

_LOGGER = logging.getLogger(__name__)

_CONNECT_TIMEOUT = 5.0
_HEARTBEAT_INTERVAL = 0.5   # seconds — matches BT ETH behaviour
_QUERY_TIMEOUT = 1.5        # seconds — max wait for a reply
_WRITE_TIMEOUT = 3.0        # writes may take longer (EEPROM commit)
_RX_MAX = 16384             # cap RX buffer size


class EmecClientError(Exception):
    """Raised when an EMEC transaction fails."""


class EmecClient:
    """Async ERMES-family ASCII client over TCP → RS-485."""

    def __init__(
        self,
        host: str,
        port: int = 8899,
        prefix: str = "34",
        slave: str = "01",
        heartbeat_interval: float = _HEARTBEAT_INTERVAL,
    ) -> None:
        self._host = host
        self._port = port
        self._prefix = prefix
        self._slave = slave
        self._hb_interval = heartbeat_interval

        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._rx = bytearray()
        self._lock = asyncio.Lock()
        self._hb_task: asyncio.Task | None = None
        self._reader_task: asyncio.Task | None = None
        self._connected = False
        self._closing = False

    # ---- lifecycle ---------------------------------------------------------

    async def connect(self) -> None:
        """Open TCP, start background tasks, prime the session."""
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, self._port),
                timeout=_CONNECT_TIMEOUT,
            )
        except (OSError, asyncio.TimeoutError) as err:
            raise EmecClientError(
                f"Cannot connect to {self._host}:{self._port}: {err}"
            ) from err

        self._connected = True
        self._closing = False
        self._rx.clear()
        self._reader_task = asyncio.create_task(self._reader_loop())
        self._hb_task = asyncio.create_task(self._heartbeat_loop())
        # Prime session so pump exits any stale state before the first query
        await asyncio.sleep(2.0)
        _LOGGER.debug("EMEC session primed at %s:%s", self._host, self._port)

    async def disconnect(self) -> None:
        """Stop background tasks and close TCP."""
        self._closing = True
        self._connected = False
        for task in (self._hb_task, self._reader_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        self._hb_task = None
        self._reader_task = None
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
            self._reader = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ---- background tasks --------------------------------------------------

    async def _reader_loop(self) -> None:
        """Continuously read bytes into the RX buffer."""
        assert self._reader is not None
        try:
            while not self._closing:
                try:
                    data = await asyncio.wait_for(
                        self._reader.read(4096), timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue
                if not data:
                    self._connected = False
                    return
                self._rx.extend(data)
                if len(self._rx) > _RX_MAX:
                    del self._rx[: len(self._rx) - _RX_MAX // 2]
        except asyncio.CancelledError:
            raise
        except Exception as err:
            _LOGGER.debug("EMEC reader loop exited: %s", err)
            self._connected = False

    async def _heartbeat_loop(self) -> None:
        """Send a keepalive every hb_interval seconds."""
        hb = f"{self._prefix}tb00 #0#\r\n".encode()
        try:
            while not self._closing:
                if self._writer is not None and self._connected:
                    try:
                        async with self._lock:
                            self._writer.write(hb)
                            await self._writer.drain()
                    except Exception as err:
                        _LOGGER.debug("Heartbeat write failed: %s", err)
                        self._connected = False
                await asyncio.sleep(self._hb_interval)
        except asyncio.CancelledError:
            raise

    # ---- frame extraction --------------------------------------------------

    def _extract_frame(self) -> bytes | None:
        """Pull the next complete frame from the RX buffer, if any."""
        while True:
            best_idx = -1
            best_term_len = 0
            for term in (b"\r\n", b"\n\r", b"\r", b"\n"):
                idx = self._rx.find(term)
                if idx >= 0 and (best_idx == -1 or idx < best_idx):
                    best_idx = idx
                    best_term_len = len(term)
            if best_idx < 0:
                return None
            frame = bytes(self._rx[:best_idx])
            del self._rx[: best_idx + best_term_len]
            if frame:
                return frame

    # ---- public API --------------------------------------------------------

    async def query(
        self,
        cmd: str,
        retries: int = 3,
        timeout_s: float = _QUERY_TIMEOUT,
    ) -> str | None:
        """Send an EMEC read command and return the matching reply text."""
        if not self._connected or self._writer is None:
            return None
        want_end = f"{cmd}end"

        async with self._lock:
            while self._extract_frame() is not None:
                pass

        frame = f"{self._prefix}{self._slave}{cmd}\r\r".encode()

        for attempt in range(retries):
            try:
                async with self._lock:
                    self._writer.write(frame)
                    await self._writer.drain()
            except Exception as err:
                _LOGGER.debug("EMEC query write failed: %s", err)
                self._connected = False
                return None

            deadline = time.monotonic() + timeout_s
            while time.monotonic() < deadline:
                await asyncio.sleep(0.05)
                f = self._extract_frame()
                while f is not None:
                    text = f.decode("ascii", errors="replace")
                    if want_end in text and "gpd" in text:
                        return text
                    f = self._extract_frame()

            _LOGGER.debug("EMEC query %s retry %d/%d", cmd, attempt + 1, retries)

        return None

    async def write(
        self,
        cmd: str,
        payload: str,
        retries: int = 2,
        timeout_s: float = _WRITE_TIMEOUT,
    ) -> bool:
        """Send an EMEC write command and confirm it was accepted.

        The pump acknowledges successful writes with '34gpd01&<cmd>okend'
        (note: no '#' separators, no 'WD' tag — different from read replies).

        Frame format:
            3401<cmd><payload><cmd>end\\r\\r
        """
        if not self._connected or self._writer is None:
            return False
        want_ok = f"{cmd}okend"

        async with self._lock:
            while self._extract_frame() is not None:
                pass

        frame = f"{self._prefix}{self._slave}{cmd}{payload}{cmd}end\r\r".encode()

        for attempt in range(retries):
            try:
                async with self._lock:
                    self._writer.write(frame)
                    await self._writer.drain()
                _LOGGER.debug("EMEC write %s: %s", cmd, payload)
            except Exception as err:
                _LOGGER.warning("EMEC write %s failed at send: %s", cmd, err)
                self._connected = False
                return False

            deadline = time.monotonic() + timeout_s
            while time.monotonic() < deadline:
                await asyncio.sleep(0.05)
                f = self._extract_frame()
                while f is not None:
                    text = f.decode("ascii", errors="replace")
                    if want_ok in text:
                        _LOGGER.info("EMEC write %s ACKed", cmd)
                        return True
                    # A "#no#changeend" or similar means rejection — abort early
                    if "no#" in text and "end" in text:
                        _LOGGER.warning("EMEC write %s REJECTED: %s", cmd, text)
                        return False
                    f = self._extract_frame()

            _LOGGER.warning(
                "EMEC write %s retry %d/%d (no ACK)", cmd, attempt + 1, retries
            )

        return False

    async def send_raw(self, raw: bytes, timeout_s: float = 1.5) -> str | None:
        """Send an arbitrary frame — diagnostic use only."""
        if not self._connected or self._writer is None:
            return None
        async with self._lock:
            while self._extract_frame() is not None:
                pass
            try:
                self._writer.write(raw)
                await self._writer.drain()
            except Exception:
                self._connected = False
                return None
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            await asyncio.sleep(0.05)
            f = self._extract_frame()
            while f is not None:
                text = f.decode("ascii", errors="replace")
                if "gpd" in text:
                    return text
                f = self._extract_frame()
        return None

    async def __aenter__(self) -> "EmecClient":
        await self.connect()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.disconnect()
