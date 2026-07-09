"""
Hayward / Silverline pool heat pump (touch-panel RS485 protocol).

Unlike the polled Modbus slaves handled by ModbusDevice, the heat pump's
control board is the Modbus MASTER: it broadcasts sensor data and polls each
peripheral for its status. We emulate the wifi-module slot (address 0x02) and
answer those polls, so this profile runs in "listener" connection mode (see
CONNECTION_MODE) driven by HaywardListener rather than by the polling
coordinator.

Protocol summary (reverse engineered; validated live on a Silverline unit):
  - broadcast sensor block : write @2001 (90 regs) -> 0x00
  - status poll            : read  @3001 (30 regs) -> 0x01 (panel) and 0x02 (us)
  - settings push          : write @1001 / @1091   -> 0x00/0x01/0x02
  Our status answer must carry reg 3009 = 0x01<addr> (device identity: panel
  0x0101, wifi slot 0x0102) and reg 3011 = a flag: 0x8000 full refresh,
  0x0004 "I have an update for 1001-1090", 0x0010 for 1091-1180. To change a
  setting we raise the flag, serve the edited block when the board reads it,
  and the board commits by resetting the flag. Temperatures are degC * 10.
"""
from __future__ import annotations

import struct
from typing import Any

from .base import ModbusDevice, RegisterDef

# ---- register addresses -----------------------------------------------------
R_STATUS, R_SET, R_XSET, R_SENS = 3001, 1001, 1091, 2001
# aliases with the REG_ prefix, used by the runtime/entity layer
REG_STATUS, REG_SET, REG_XSET = R_STATUS, R_SET, R_XSET
A_STATUS = b"\x0b\xb9"   # 3001
A_SET = b"\x03\xe9"      # 1001
A_XSET = b"\x04\x43"     # 1091
FLAG_SET, FLAG_XSET, FLAG_REFRESH = 0x0004, 0x0010, 0x8000

# settings registers
REG_POWER = 1011         # 0=off 1=on (changes together with 1014)
REG_POWER2 = 1014
REG_MODE = 1012          # 0=cool 1=heat 2=auto
REG_SETPOINT = 1013      # current setpoint, degC*10
SAVED_TEMP = {0: 1135, 1: 1136, 2: 1137}   # per-mode memorised setpoint (block 1091)

MODE_COOL, MODE_HEAT, MODE_AUTO = 0, 1, 2

# sensor block: key, label, unit, device_class, register, scale
HAYWARD_SENSORS: list[tuple[str, str, str, str | None, int, float]] = [
    ("water_inlet", "Water inlet", "°C", "temperature", 2046, 0.1),
    ("water_outlet", "Water outlet", "°C", "temperature", 2047, 0.1),
    ("suction", "Suction", "°C", "temperature", 2045, 0.1),
    ("coil", "Coil", "°C", "temperature", 2048, 0.1),
    ("ambient", "Ambient", "°C", "temperature", 2049, 0.1),
    ("exhaust", "Exhaust", "°C", "temperature", 2050, 0.1),
    ("compressor_current", "Compressor current", "A", "current", 2051, 1.0),
    ("ac_voltage", "AC voltage", "V", "voltage", 2063, 1.0),
    ("fan_speed", "Fan speed", "rpm", None, 2067, 1.0),
]

# per-mode memorised setpoints (settings block 1091) — diagnostic, read-only
HAYWARD_SETTING_SENSORS: list[tuple[str, str, str, str | None, int, float]] = [
    ("memo_cool", "Cool setpoint memory", "°C", "temperature", 1135, 0.1),
    ("memo_heat", "Heat setpoint memory", "°C", "temperature", 1136, 0.1),
    ("memo_auto", "Auto setpoint memory", "°C", "temperature", 1137, 0.1),
]


def crc16(data: bytes) -> bytes:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return struct.pack("<H", crc)


def crc_ok(frame: bytes) -> bool:
    return len(frame) >= 4 and crc16(frame[:-2]) == frame[-2:]


def framed(payload: bytes) -> bytes:
    return payload + crc16(payload)


def next_frame(buf: bytes) -> tuple[bytes | None, int, bool]:
    """Split one Modbus RTU frame off the front of a raw stream.

    Returns (frame, consumed, need_more). The short (8-byte request) length is
    tried first so an 8-byte poll parses the instant it arrives instead of
    waiting for the longer "response" interpretation to fill.
    """
    if len(buf) < 2:
        return None, 0, True
    a, fn = buf[0], buf[1]
    if a in (0, 1, 2) and fn in (3, 16):
        cands = [8]
        if fn == 3 and len(buf) >= 3:
            cands.append(3 + buf[2] + 2)
        if fn == 16 and len(buf) >= 7:
            cands.append(7 + buf[6] + 2)
        any_bigger = False
        for length in cands:
            if length < 4:
                continue
            if length <= len(buf):
                if crc_ok(buf[:length]):
                    return bytes(buf[:length]), length, False
            else:
                any_bigger = True
        if any_bigger:
            return None, 0, True
    return None, 1, False


def _regs(payload: bytes) -> list[int]:
    return [(payload[i] << 8) | payload[i + 1] for i in range(0, len(payload) - 1, 2)]


def _pack(regs: list[int]) -> bytes:
    out = bytearray()
    for r in regs:
        out += bytes([(r >> 8) & 0xFF, r & 0xFF])
    return bytes(out)


def _bcd(v: int) -> int:
    return ((v // 10) << 4) | (v % 10)


class HaywardProtocol:
    """Pure protocol engine. Feed it bus bytes, get reply frames back.

    No I/O and no HA dependency, so it is unit-testable off-target. The
    reply hold-off (the board keeps its RS485 driver asserted after polling)
    is applied by the caller, not here.
    """

    def __init__(self, address: int = 2, id_field: int = 0) -> None:
        self.address = address
        self.id_field = id_field          # reg 3009; 0 -> auto (0x0100 | address)
        self.rx = bytearray()
        self.status_tmpl: bytes | None = None
        self.block: dict[int, list[int] | None] = {R_SET: None, R_XSET: None}
        self.state: dict[int, int] = {}
        self.queue: list[dict[str, Any]] = []
        self.active: dict[str, Any] | None = None
        self.active_polls = 0
        # one-shot callbacks the runtime consumes
        self.dirty = False                # state changed -> refresh entities
        self.last_commit: dict[int, int] | None = None
        self.block_changes: list[tuple[int, list[tuple[int, int, int]]]] = []  # RE aid

    # ---- passive mirroring --------------------------------------------------
    def observe(self, f: bytes) -> None:
        a, fn = f[0], f[1]
        if fn == 3 and a == 1 and len(f) == 65 and f[3 + 18:3 + 20] == A_STATUS:
            self.status_tmpl = f[3:63]
        if fn == 16 and len(f) > 8:
            start = (f[2] << 8) | f[3]
            qty = (f[4] << 8) | f[5]
            self._store(start, _regs(f[7:7 + qty * 2]))

    def _store(self, start: int, regs: list[int]) -> None:
        if start in (R_SET, R_XSET) and len(regs) >= 90:
            new = list(regs[:90])
            prev = self.block[start]
            if prev is not None:
                diffs = [(start + i, prev[i], new[i]) for i in range(90) if prev[i] != new[i]]
                if diffs:
                    self.block_changes.append((start, diffs))
            self.block[start] = new
        for i, v in enumerate(regs):
            self.state[start + i] = v
        self.dirty = True

    def need_refresh(self) -> bool:
        return self.block[R_SET] is None or self.block[R_XSET] is None

    def ready(self) -> bool:
        return (self.status_tmpl is not None
                and self.block[R_SET] is not None
                and self.block[R_XSET] is not None)

    def controllable(self) -> bool:
        # Enough to drive the climate entity: the setpoint/mode/power block plus
        # a status template. The 1091 block only carries the per-mode memories.
        return self.status_tmpl is not None and self.block[R_SET] is not None

    def reg(self, address: int) -> int | None:
        return self.state.get(address)

    # ---- frame builders -----------------------------------------------------
    def _status_body(self, flag: int) -> bytes:
        if self.status_tmpl is not None:
            data = bytearray(self.status_tmpl)
        else:
            data = bytearray(60)
            data[18], data[19] = 0x0B, 0xB9          # reg 3010 = 3001
        import time
        t = time.localtime()
        data[29], data[31], data[33] = _bcd(t.tm_hour), _bcd(t.tm_min), _bcd(t.tm_sec)
        # reg 3009 = device identity. The board only honours our refresh/commands
        # when we present the wifi-slot identity 0x01<addr> (= 0x0102 for addr 2);
        # cloning the panel value (0x0101) is ignored. Confirmed live: the working
        # command run used --id-field 0102.
        idf = self.id_field or (0x0100 | self.address)
        data[16], data[17] = (idf >> 8) & 0xFF, idf & 0xFF
        data[20], data[21] = (flag >> 8) & 0xFF, flag & 0xFF   # reg 3011 = flag
        return bytes(data)

    def _status_frame(self, flag: int) -> bytes:
        return framed(bytes([self.address, 0x03, 0x3C]) + self._status_body(flag))

    def _block_frame(self, addr_reg: int, edits: dict[int, int]) -> bytes:
        regs = list(self.block[addr_reg])   # type: ignore[arg-type]
        for reg, val in edits.items():
            regs[reg - addr_reg] = val
        return framed(bytes([self.address, 0x03, 0xB4]) + _pack(regs))

    # ---- commands -----------------------------------------------------------
    def queue_temp(self, celsius: float) -> bool:
        v = int(round(celsius * 10))
        if not self._enqueue(FLAG_SET, R_SET, {REG_SETPOINT: v}):
            return False
        mode = self.state.get(REG_MODE, MODE_HEAT)
        self._enqueue(FLAG_XSET, R_XSET, {SAVED_TEMP[mode]: v})
        return True

    def queue_power(self, on: bool) -> bool:
        v = 1 if on else 0
        return self._enqueue(FLAG_SET, R_SET, {REG_POWER: v, REG_POWER2: v})

    def queue_mode(self, mode: int) -> bool:
        # Exactly like the validated script: a single write to reg 1012.
        return self._enqueue(FLAG_SET, R_SET, {REG_MODE: mode})

    def _enqueue(self, flag: int, addr_reg: int, edits: dict[int, int]) -> bool:
        if self.block[addr_reg] is None:
            return False
        self.queue.append({"flag": flag, "addr_reg": addr_reg, "edits": edits})
        return True

    # ---- per-frame handler --------------------------------------------------
    def feed(self, chunk: bytes) -> list[bytes]:
        """Add bytes, return the list of reply frames to send (usually 0 or 1)."""
        self.rx += chunk
        if len(self.rx) > 1024:
            del self.rx[:-256]
        replies: list[bytes] = []
        while True:
            frame, used, need = next_frame(bytes(self.rx))
            if need:
                break
            del self.rx[:used]
            if frame:
                r = self._handle(frame)
                if r is not None:
                    replies.append(r)
        return replies

    def _handle(self, f: bytes) -> bytes | None:
        self.observe(f)
        a, fn = f[0], f[1]
        if a != self.address:
            return None
        if self.active is None and self.queue:
            self.active = dict(self.queue.pop(0))
            self.active["served"] = False
            self.active_polls = 0

        head6 = f[:6]
        if fn == 3 and head6 == bytes([self.address, 3]) + A_STATUS + b"\x00\x1e":
            if self.need_refresh():
                return self._status_frame(FLAG_REFRESH)
            flag = self.active["flag"] if self.active else 0x0000
            if self.active:
                self.active_polls += 1
                if self.active_polls > 12 and not self.active["served"]:
                    self.active = None
                    flag = 0x0000
            return self._status_frame(flag)

        if fn == 3 and head6 in (bytes([self.address, 3]) + A_SET + b"\x00\x5a",
                                 bytes([self.address, 3]) + A_XSET + b"\x00\x5a"):
            reg = R_SET if head6[2:4] == A_SET else R_XSET
            if self.active and self.active["addr_reg"] == reg:
                self.active["served"] = True
                return self._block_frame(reg, self.active["edits"])
            return None

        if fn == 16 and len(f) > 8:
            start = (f[2] << 8) | f[3]
            ack = framed(f[:6])
            if start == R_STATUS and self.active and self.active["served"]:
                # Reflect the committed change into our mirror immediately, so a
                # back-to-back batch (e.g. power-on then mode) builds on the new
                # state instead of re-serving the stale block and undoing it.
                addr_reg = self.active["addr_reg"]
                blk = self.block.get(addr_reg)
                for reg, val in self.active["edits"].items():
                    if blk is not None:
                        blk[reg - addr_reg] = val
                    self.state[reg] = val
                self.last_commit = dict(self.active["edits"])
                self.active = None
            return ack
        return None


class HaywardHeatPump(ModbusDevice):
    """Config-flow profile for the Hayward pool heat pump (listener mode)."""

    DEVICE_KEY = "hayward_heat_pump"
    DEVICE_NAME = "Hayward pool heat pump"
    MODBUS_ADDRESS = 0x02
    FIXED_ADDRESS = 0x02                        # structural: the wifi-module slot
    READ_REGISTERS: list[RegisterDef] = []     # not polled
    CONNECTION_MODE = "listener"               # routed to HaywardListener

    def __init__(self, name: str = "") -> None:
        self.name = name

    # kept only so the abstract base is satisfied; never used in listener mode
    async def set_speed(self, client: Any, speed_pct: int) -> bool:  # noqa: ARG002
        return False
