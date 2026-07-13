"""
EMEC WDPHRH pH/Redox pool controller — device profile with full write support.

Reverse-engineered live 2026-07-13 via four isolated Nimbus write sessions.
All setpoint / parameter / probe-failure / dosing-alarm / max-strokes /
flow / DI-config / reset writes are supported.

Read commands (fixed-width fields separated by '#'):

  valuer  : #<pH:4>#<mV:4>#<dose:3>#<flag:1>#
  setpntr : #<ph_hi:4>#<ph_lo:4>#<ph_hi_pct:3>#<ph_lo_pct:3>
            #<ph_wait:2>#<ph_wm:1>#<mv_lo:4>#<mv_hi:4>
            #<mv_lo_pct:3>#<mv_hi_pct:3>#<mv_wait:2>#<mv_wm:1>#
  alldosr : #<ph_alrm_en:1>#<ph_alrm_min:3>#<mv_alrm_en:1>#<mv_alrm_min:3>#
  allrmr  : #<a1:1>#..#<a8:1>#
  outptr  : #<out1:1>#<out2:1>#<out3:1>#
  flowstr : #<mode:1>#<time:2>#
  diginpr : #<standby:1>#<ph_level:1>#<mv_level:1>#     0=N.O., 1=N.C.
  servicr : #<offset>#<hours>#
  setstkr : #<ph_strokes:3>#<mv_strokes:3>#
  paramtr : #<passcode:4>#<feed_delay:2>#<priority:1>#
  allprbr : #<ph_mode:1>#<ph_min:3>#<mv_mode:1>#<mv_min:3>#

Write commands (payload = read fields concatenated WITHOUT '#'):

  setpnw <34>  setpntr fields    wm: 0=PROP, 1=ON/OFF
  alldow  <8>  alldosr fields
  setskw  <6>  setstkr fields
  paramw  <9>  passcode(4)+feed(2)+prio(1)+tau(2)   tau not in read
  clockw <15>  HH MM SS fmt(1) ?(1) DD MM YY ?(1)
  allprw  <8>  mode(1)+min(3) x2      min=000 disabled, 100-250 active
                                     mode: 0=DOSE, 1=STOP
  flowsw  <3>  mode(1)+time(2)        mode: 0=Disable, 1=Reverse, 2=Direct
  diginw  <3>  standby+ph_lvl+mv_lvl  0=N.O., 1=N.C.
  resalw  <1>  single space, resets latched alarms

Alarm map (allrmr, confirmed):
  a1=pH- empty, a2=chlorine empty, a3=no flow, a8=standby, a4..7=unknown
"""
from __future__ import annotations

import logging
from typing import Any

from .base import DeviceData

_LOGGER = logging.getLogger(__name__)


_READ_COMMANDS: list[tuple[str, str, bool]] = [
    ("valuer",  "decode_valuer",  True),
    ("setpntr", "decode_setpntr", False),
    ("alldosr", "decode_alldosr", False),
    ("allrmr",  "decode_allrmr",  False),
    ("outptr",  "decode_outptr",  False),
    ("flowstr", "decode_flowstr", False),
    ("diginpr", "decode_diginpr", False),
    ("servicr", "decode_servicr", False),
    ("setstkr", "decode_setstkr", False),
    ("paramtr", "decode_paramtr", False),
    ("allprbr", "decode_allprbr", False),
]


def _split_payload(rsp: str) -> list[str] | None:
    if "&WD" not in rsp or "end" not in rsp:
        return None
    body = rsp.split("&WD", 1)[1]
    tail = body.rfind("#")
    if tail < 0:
        return None
    return body[:tail].split("#")


def _to_int(s: str) -> int | None:
    try:
        return int(s)
    except (ValueError, TypeError):
        return None


# ---- Decoders ---------------------------------------------------------------

def decode_valuer(rsp: str) -> dict[str, Any]:
    f = _split_payload(rsp)
    if f is None or len(f) < 5:
        return {}
    ph_raw = _to_int(f[1])
    return {
        "ph":               ph_raw / 100.0 if ph_raw is not None else None,
        "mv":               _to_int(f[2]),
        "current_dose_pct": _to_int(f[3]),
        "value_flag":       f[4],
    }


def decode_setpntr(rsp: str) -> dict[str, Any]:
    f = _split_payload(rsp)
    if f is None or len(f) < 13:
        return {}

    def ph(idx: int) -> float | None:
        v = _to_int(f[idx])
        return v / 100.0 if v is not None else None

    return {
        "ph_high_sp":       ph(1),
        "ph_low_sp":        ph(2),
        "ph_high_pct":      _to_int(f[3]),
        "ph_low_pct":       _to_int(f[4]),
        "ph_waiting_time":  _to_int(f[5]),
        "ph_working_mode":  _to_int(f[6]),
        "mv_low_sp":        _to_int(f[7]),
        "mv_high_sp":       _to_int(f[8]),
        "mv_low_pct":       _to_int(f[9]),
        "mv_high_pct":      _to_int(f[10]),
        "mv_waiting_time":  _to_int(f[11]),
        "mv_working_mode":  _to_int(f[12]),
    }


def decode_alldosr(rsp: str) -> dict[str, Any]:
    """Dosing alarm: mode + minutes per channel.

    Same layout as probe failure (allprbr):
      min = 0    → feature DISABLED
      min > 0    → feature ENABLED, alarm after N continuous dosing minutes
      mode       → 0=DOSE, 1=STOP (persistent even when disabled)
    """
    f = _split_payload(rsp)
    if f is None or len(f) < 5:
        return {}
    ph_min = _to_int(f[2]) or 0
    mv_min = _to_int(f[4]) or 0
    return {
        "dosing_alarm_ph_mode":    f[1],
        "dosing_alarm_ph_minutes": ph_min,
        "dosing_alarm_ph_enabled": ph_min > 0,
        "dosing_alarm_mv_mode":    f[3],
        "dosing_alarm_mv_minutes": mv_min,
        "dosing_alarm_mv_enabled": mv_min > 0,
    }


def decode_allrmr(rsp: str) -> dict[str, Any]:
    f = _split_payload(rsp)
    if f is None or len(f) < 9:
        return {}
    flags = [bool(_to_int(x) or 0) for x in f[1:9]]
    return {
        "alarm_ph_empty":       flags[0],
        "alarm_chlorine_empty": flags[1],
        "alarm_no_flow":        flags[2],
        "alarm_a4":             flags[3],
        "alarm_a5":             flags[4],
        "alarm_a6":             flags[5],
        "alarm_a7":             flags[6],
        "alarm_standby":        flags[7],
    }


def decode_outptr(rsp: str) -> dict[str, Any]:
    f = _split_payload(rsp)
    if f is None or len(f) < 4:
        return {}
    return {
        "out1": bool(_to_int(f[1]) or 0),
        "out2": bool(_to_int(f[2]) or 0),
        "out3": bool(_to_int(f[3]) or 0),
    }


def decode_flowstr(rsp: str) -> dict[str, Any]:
    f = _split_payload(rsp)
    if f is None or len(f) < 3:
        return {}
    return {"flow_mode": _to_int(f[1]), "flow_time": _to_int(f[2])}


def decode_diginpr(rsp: str) -> dict[str, Any]:
    f = _split_payload(rsp)
    if f is None or len(f) < 4:
        return {}
    return {
        "di_standby_nc":  bool(_to_int(f[1]) or 0),
        "di_ph_level_nc": bool(_to_int(f[2]) or 0),
        "di_mv_level_nc": bool(_to_int(f[3]) or 0),
    }


def decode_servicr(rsp: str) -> dict[str, Any]:
    f = _split_payload(rsp)
    if f is None or len(f) < 3:
        return {}
    return {"service_offset": _to_int(f[1]), "service_hours": _to_int(f[2])}


def decode_setstkr(rsp: str) -> dict[str, Any]:
    f = _split_payload(rsp)
    if f is None or len(f) < 3:
        return {}
    return {
        "max_strokes_ph": _to_int(f[1]),
        "max_strokes_mv": _to_int(f[2]),
    }


def decode_paramtr(rsp: str) -> dict[str, Any]:
    """Parameters: passcode + feeding delay (min) + priority mode."""
    f = _split_payload(rsp)
    if f is None or len(f) < 4:
        return {}
    return {
        "passcode":      _to_int(f[1]),
        "feeding_delay": _to_int(f[2]),
        "priority":      _to_int(f[3]),
    }


def decode_allprbr(rsp: str) -> dict[str, Any]:
    """Probe failure detection: mode + minutes per channel."""
    f = _split_payload(rsp)
    if f is None or len(f) < 5:
        return {}
    ph_min = _to_int(f[2]) or 0
    mv_min = _to_int(f[4]) or 0
    return {
        "probe_failure_ph_mode":    f[1],
        "probe_failure_ph_minutes": ph_min,
        "probe_failure_ph_enabled": ph_min > 0,
        "probe_failure_mv_mode":    f[3],
        "probe_failure_mv_minutes": mv_min,
        "probe_failure_mv_enabled": mv_min > 0,
    }


_DECODERS = {
    "decode_valuer":  decode_valuer,
    "decode_setpntr": decode_setpntr,
    "decode_alldosr": decode_alldosr,
    "decode_allrmr":  decode_allrmr,
    "decode_outptr":  decode_outptr,
    "decode_flowstr": decode_flowstr,
    "decode_diginpr": decode_diginpr,
    "decode_servicr": decode_servicr,
    "decode_setstkr": decode_setstkr,
    "decode_paramtr": decode_paramtr,
    "decode_allprbr": decode_allprbr,
}


# ============================================================================
# Write encoding
# ============================================================================

FIELD_WIDTHS: dict[str, list[int]] = {
    "setpntr": [4, 4, 3, 3, 2, 1, 4, 4, 3, 3, 2, 1],
    "alldosr": [1, 3, 1, 3],
    "setstkr": [3, 3],
    "flowstr": [1, 2],
    "diginpr": [1, 1, 1],
    "allprbr": [1, 3, 1, 3],
}

PARAMW_DEFAULT_TAU = "00"

READ_TO_WRITE: dict[str, str] = {
    "setpntr": "setpnw",
    "alldosr": "alldow",
    "setstkr": "setskw",
    "flowstr": "flowsw",
    "diginpr": "diginw",
    "allprbr": "allprw",
    "paramtr": "paramw",
}


def _extract_field_values(rsp: str, read_cmd: str) -> list[str] | None:
    parts = _split_payload(rsp)
    if parts is None:
        return None
    widths = FIELD_WIDTHS.get(read_cmd)
    if widths is None or len(parts) < len(widths) + 1:
        return None
    return list(parts[1 : 1 + len(widths)])


def _encode_payload(read_cmd: str, values: list[str]) -> str:
    widths = FIELD_WIDTHS.get(read_cmd)
    if widths is None or len(values) != len(widths):
        raise ValueError(f"Field count mismatch for {read_cmd}")
    out = []
    for v, w in zip(values, widths):
        s = str(v)
        if len(s) > w:
            raise ValueError(f"Value {s!r} exceeds width {w}")
        out.append(s.rjust(w, "0"))
    return "".join(out)


FIELD_INDEX: dict[str, dict[str, int]] = {
    "setpntr": {
        "ph_high_sp":      0,
        "ph_low_sp":       1,
        "ph_high_pct":     2,
        "ph_low_pct":      3,
        "ph_waiting_time": 4,
        "ph_working_mode": 5,
        "mv_low_sp":       6,
        "mv_high_sp":      7,
        "mv_low_pct":      8,
        "mv_high_pct":     9,
        "mv_waiting_time": 10,
        "mv_working_mode": 11,
    },
    "alldosr": {
        "dosing_alarm_ph_mode":    0,
        "dosing_alarm_ph_minutes": 1,
        "dosing_alarm_mv_mode":    2,
        "dosing_alarm_mv_minutes": 3,
    },
    "setstkr": {"max_strokes_ph": 0, "max_strokes_mv": 1},
    "flowstr": {"flow_mode": 0, "flow_time": 1},
    "diginpr": {
        "di_standby_nc":  0,
        "di_ph_level_nc": 1,
        "di_mv_level_nc": 2,
    },
    "allprbr": {
        "probe_failure_ph_mode":    0,
        "probe_failure_ph_minutes": 1,
        "probe_failure_mv_mode":    2,
        "probe_failure_mv_minutes": 3,
    },
}


def encode_field_value(read_cmd: str, key: str, value: Any) -> str:
    if read_cmd == "setpntr" and key.endswith("_sp"):
        if key.startswith("ph_"):
            return f"{int(round(float(value) * 100)):04d}"
        if key.startswith("mv_"):
            return f"{int(round(float(value))):04d}"
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(int(value)) if not isinstance(value, str) else value


# ---- Device profile ---------------------------------------------------------

class EmecWdphrh:
    DEVICE_KEY          = "emec_wdphrh"
    DEVICE_NAME         = "EMEC WDPHRH"
    DEVICE_MANUFACTURER = "EMEC"
    CONNECTION_MODE     = "emec_poller"
    DEFAULT_ADDRESS     = 1

    def __init__(self, name: str = "") -> None:
        self._name = name
        self._last_reads: dict[str, str] = {}
        self._last_tau: str = PARAMW_DEFAULT_TAU

    async def poll(self, client) -> DeviceData:
        data = DeviceData()
        for cmd, decoder_name, essential in _READ_COMMANDS:
            rsp = await client.query(cmd, retries=2, timeout_s=1.5)
            data.raw[cmd] = rsp
            if rsp is None:
                if essential:
                    _LOGGER.debug("EMEC essential cmd %s unanswered", cmd)
                continue
            self._last_reads[cmd] = rsp
            decoded = _DECODERS[decoder_name](rsp)
            if decoded:
                data.values.update(decoded)
                data.online = True
        return data

    async def write_field(self, client, read_cmd: str, key: str, value: Any) -> bool:
        if read_cmd == "paramtr":
            return await self._write_paramw_field(client, key, value)

        write_cmd = READ_TO_WRITE.get(read_cmd)
        if write_cmd is None:
            _LOGGER.error("No write command mapped for %s", read_cmd)
            return False

        rsp = await client.query(read_cmd, retries=2, timeout_s=1.5)
        if rsp is None:
            rsp = self._last_reads.get(read_cmd)
        if rsp is None:
            _LOGGER.error("EMEC write %s: cannot obtain current values", read_cmd)
            return False

        values = _extract_field_values(rsp, read_cmd)
        if values is None:
            _LOGGER.error("EMEC write %s: cannot parse fields", read_cmd)
            return False

        idx_map = FIELD_INDEX.get(read_cmd, {})
        if key not in idx_map:
            _LOGGER.error("EMEC write: unknown field %s.%s", read_cmd, key)
            return False

        values[idx_map[key]] = encode_field_value(read_cmd, key, value)
        payload = _encode_payload(read_cmd, values)
        return await client.write(write_cmd, payload)

    async def _write_paramw_field(self, client, key: str, value: Any) -> bool:
        rsp = await client.query("paramtr", retries=2, timeout_s=1.5)
        if rsp is None:
            rsp = self._last_reads.get("paramtr")
        if rsp is None:
            return False
        f = _split_payload(rsp)
        if f is None or len(f) < 4:
            return False

        values = [
            f[1].rjust(4, "0"),
            f[2].rjust(2, "0"),
            f[3].rjust(1, "0"),
            self._last_tau.rjust(2, "0"),
        ]
        idx_map = {"passcode": 0, "feeding_delay": 1, "priority": 2, "tau": 3}
        if key not in idx_map:
            return False
        idx = idx_map[key]
        if key == "passcode":
            values[idx] = f"{max(0, min(9999, int(value))):04d}"
        elif key == "feeding_delay":
            values[idx] = f"{max(0, min(60, int(value))):02d}"
        elif key == "priority":
            values[idx] = f"{max(1, min(3, int(value))):d}"
        elif key == "tau":
            values[idx] = f"{max(0, min(99, int(value))):02d}"
            self._last_tau = values[idx]
        payload = "".join(values)
        return await client.write("paramw", payload)

    async def reset_all_alarms(self, client) -> bool:
        return await client.write("resalw", " ")

    async def sync_clock(self, client) -> bool:
        """Send the current HA time via clockw.

        Format: HH MM SS fmt(1=Europe24h) ?(0) DD MM YY ?(0)  (15 chars)
        """
        import datetime as _dt
        now = _dt.datetime.now()
        payload = (
            f"{now.hour:02d}{now.minute:02d}{now.second:02d}"
            f"1"
            f"0"
            f"{now.day:02d}{now.month:02d}{now.year % 100:02d}"
            f"0"
        )
        return await client.write("clockw", payload)

    @property
    def sensor_keys(self) -> list[str]:
        return list(SENSOR_DESCRIPTIONS.keys())

    @property
    def binary_sensor_keys(self) -> list[str]:
        return list(BINARY_SENSOR_DESCRIPTIONS.keys())

    @property
    def number_keys(self) -> list[str]:
        return list(NUMBER_DESCRIPTIONS.keys())

    @property
    def switch_keys(self) -> list[str]:
        return list(SWITCH_DESCRIPTIONS.keys())

    @property
    def select_keys(self) -> list[str]:
        return list(SELECT_DESCRIPTIONS.keys())

    @property
    def name(self) -> str:
        return self._name


# ============================================================================
# HA entity descriptions
# ============================================================================

SENSOR_DESCRIPTIONS: dict[str, dict] = {
    "ph": {
        "name": "pH", "native_unit": None, "icon": "mdi:ph",
        "state_class": "measurement", "device_class": "ph",
        "diagnostic": False,
    },
    "mv": {
        "name": "Redox", "native_unit": "mV", "icon": "mdi:flash-triangle",
        "state_class": "measurement", "device_class": "voltage",
        "diagnostic": False,
    },
    "current_dose_pct": {
        "name": "valuer field 3 (unconfirmed)", "native_unit": None,
        "icon": "mdi:code-braces",
        "state_class": None, "device_class": None,
        "diagnostic": True,
    },
    "value_flag": {
        "name": "valuer field 4 (raw)", "native_unit": None,
        "icon": "mdi:code-braces",
        "state_class": None, "device_class": None,
        "diagnostic": True,
    },
    "service_hours": {
        "name": "Service counter", "native_unit": "h",
        "icon": "mdi:timer-outline", "state_class": "total_increasing",
        "device_class": None, "diagnostic": True,
    },
    "service_offset": {
        "name": "Service offset", "native_unit": None,
        "icon": "mdi:tune", "state_class": "measurement",
        "device_class": None, "diagnostic": True,
    },
}


NUMBER_DESCRIPTIONS: dict[str, dict] = {
    "ph_high_sp": {
        "name": "pH high setpoint", "unit": None, "icon": "mdi:target",
        "device_class": "ph",
        "min_value": 0.0, "max_value": 14.0, "step": 0.05,
        "read_cmd": "setpntr", "field": "ph_high_sp",
    },
    "ph_low_sp": {
        "name": "pH low setpoint", "unit": None, "icon": "mdi:target",
        "device_class": "ph",
        "min_value": 0.0, "max_value": 14.0, "step": 0.05,
        "read_cmd": "setpntr", "field": "ph_low_sp",
    },
    "ph_high_pct": {
        "name": "pH high dose %", "unit": "%", "icon": "mdi:percent",
        "device_class": None,
        "min_value": 0, "max_value": 100, "step": 1,
        "read_cmd": "setpntr", "field": "ph_high_pct",
    },
    "ph_low_pct": {
        "name": "pH low dose %", "unit": "%", "icon": "mdi:percent",
        "device_class": None,
        "min_value": 0, "max_value": 100, "step": 1,
        "read_cmd": "setpntr", "field": "ph_low_pct",
    },
    "ph_waiting_time": {
        "name": "pH waiting time", "unit": "min",
        "icon": "mdi:timer-sand", "device_class": None,
        "min_value": 0, "max_value": 99, "step": 1,
        "read_cmd": "setpntr", "field": "ph_waiting_time",
    },
    "mv_low_sp": {
        "name": "Redox low setpoint", "unit": "mV", "icon": "mdi:target",
        "device_class": "voltage",
        "min_value": 0, "max_value": 999, "step": 5,
        "read_cmd": "setpntr", "field": "mv_low_sp",
    },
    "mv_high_sp": {
        "name": "Redox high setpoint", "unit": "mV", "icon": "mdi:target",
        "device_class": "voltage",
        "min_value": 0, "max_value": 999, "step": 5,
        "read_cmd": "setpntr", "field": "mv_high_sp",
    },
    "mv_low_pct": {
        "name": "Redox low dose %", "unit": "%", "icon": "mdi:percent",
        "device_class": None,
        "min_value": 0, "max_value": 100, "step": 1,
        "read_cmd": "setpntr", "field": "mv_low_pct",
    },
    "mv_high_pct": {
        "name": "Redox high dose %", "unit": "%", "icon": "mdi:percent",
        "device_class": None,
        "min_value": 0, "max_value": 100, "step": 1,
        "read_cmd": "setpntr", "field": "mv_high_pct",
    },
    "mv_waiting_time": {
        "name": "Redox waiting time", "unit": "min",
        "icon": "mdi:timer-sand", "device_class": None,
        "min_value": 0, "max_value": 99, "step": 1,
        "read_cmd": "setpntr", "field": "mv_waiting_time",
    },
    "max_strokes_ph": {
        "name": "Max strokes pH", "unit": "P/m", "icon": "mdi:pump",
        "device_class": None,
        "min_value": 1, "max_value": 180, "step": 1,
        "read_cmd": "setstkr", "field": "max_strokes_ph",
    },
    "max_strokes_mv": {
        "name": "Max strokes Redox", "unit": "P/m", "icon": "mdi:pump",
        "device_class": None,
        "min_value": 1, "max_value": 180, "step": 1,
        "read_cmd": "setstkr", "field": "max_strokes_mv",
    },
    "passcode": {
        "name": "Passcode", "unit": None, "icon": "mdi:key",
        "device_class": None,
        "min_value": 0, "max_value": 9999, "step": 1,
        "read_cmd": "paramtr", "field": "passcode",
    },
    "feeding_delay": {
        "name": "Feeding delay", "unit": "min", "icon": "mdi:timer-outline",
        "device_class": None,
        "min_value": 0, "max_value": 60, "step": 1,
        "read_cmd": "paramtr", "field": "feeding_delay",
    },
    "dosing_alarm_ph_minutes": {
        "name": "Dosing alarm pH threshold", "unit": "min",
        "icon": "mdi:alarm", "device_class": None,
        "min_value": 0, "max_value": 999, "step": 1,
        "read_cmd": "alldosr", "field": "dosing_alarm_ph_minutes",
    },
    "dosing_alarm_mv_minutes": {
        "name": "Dosing alarm Redox threshold", "unit": "min",
        "icon": "mdi:alarm", "device_class": None,
        "min_value": 0, "max_value": 999, "step": 1,
        "read_cmd": "alldosr", "field": "dosing_alarm_mv_minutes",
    },
    "probe_failure_ph_minutes": {
        "name": "Probe failure pH threshold", "unit": "min",
        "icon": "mdi:alarm-check", "device_class": None,
        "min_value": 0, "max_value": 250, "step": 1,
        "read_cmd": "allprbr", "field": "probe_failure_ph_minutes",
    },
    "probe_failure_mv_minutes": {
        "name": "Probe failure Redox threshold", "unit": "min",
        "icon": "mdi:alarm-check", "device_class": None,
        "min_value": 0, "max_value": 250, "step": 1,
        "read_cmd": "allprbr", "field": "probe_failure_mv_minutes",
    },
    "flow_time": {
        "name": "Flow time", "unit": "min", "icon": "mdi:clock-outline",
        "device_class": None,
        "min_value": 0, "max_value": 99, "step": 1,
        "read_cmd": "flowstr", "field": "flow_time",
    },
}


BINARY_SENSOR_DESCRIPTIONS: dict[str, dict] = {
    "alarm_ph_empty": {
        "name": "pH- reservoir empty", "icon": "mdi:water-off",
        "device_class": "problem", "diagnostic": False,
    },
    "alarm_chlorine_empty": {
        "name": "Chlorine reservoir empty", "icon": "mdi:water-off",
        "device_class": "problem", "diagnostic": False,
    },
    "alarm_no_flow": {
        "name": "No flow", "icon": "mdi:water-off",
        "device_class": "problem", "diagnostic": False,
    },
    "alarm_standby": {
        "name": "Standby", "icon": "mdi:power-standby",
        "device_class": None, "diagnostic": False,
    },
    "out1": {"name": "Output 1", "icon": "mdi:electric-switch",
             "device_class": None, "diagnostic": True},
    "out2": {"name": "Output 2", "icon": "mdi:electric-switch",
             "device_class": None, "diagnostic": True},
    "out3": {"name": "Output 3", "icon": "mdi:electric-switch",
             "device_class": None, "diagnostic": True},
    "alarm_a4": {"name": "Alarm 4 (unknown)", "icon": "mdi:alert-outline",
                 "device_class": "problem", "diagnostic": True},
    "alarm_a5": {"name": "Alarm 5 (unknown)", "icon": "mdi:alert-outline",
                 "device_class": "problem", "diagnostic": True},
    "alarm_a6": {"name": "Alarm 6 (unknown)", "icon": "mdi:alert-outline",
                 "device_class": "problem", "diagnostic": True},
    "alarm_a7": {"name": "Alarm 7 (unknown)", "icon": "mdi:alert-outline",
                 "device_class": "problem", "diagnostic": True},
    "dosing_alarm_ph_enabled": {
        "name": "Dosing alarm pH enabled", "icon": "mdi:alarm",
        "device_class": None, "diagnostic": True,
    },
    "dosing_alarm_mv_enabled": {
        "name": "Dosing alarm Redox enabled", "icon": "mdi:alarm",
        "device_class": None, "diagnostic": True,
    },
    "probe_failure_ph_enabled": {
        "name": "Probe failure pH enabled", "icon": "mdi:alarm-check",
        "device_class": None, "diagnostic": True,
    },
    "probe_failure_mv_enabled": {
        "name": "Probe failure Redox enabled", "icon": "mdi:alarm-check",
        "device_class": None, "diagnostic": True,
    },
}


SWITCH_DESCRIPTIONS: dict[str, dict] = {
    "di_standby_nc": {
        "name": "DI Standby is N.C.", "icon": "mdi:electric-switch-closed",
        "read_cmd": "diginpr", "field": "di_standby_nc",
    },
    "di_ph_level_nc": {
        "name": "DI pH level is N.C.", "icon": "mdi:electric-switch-closed",
        "read_cmd": "diginpr", "field": "di_ph_level_nc",
    },
    "di_mv_level_nc": {
        "name": "DI Redox level is N.C.", "icon": "mdi:electric-switch-closed",
        "read_cmd": "diginpr", "field": "di_mv_level_nc",
    },
}


SELECT_DESCRIPTIONS: dict[str, dict] = {
    "ph_working_mode": {
        "name": "pH working mode", "icon": "mdi:swap-horizontal",
        "read_cmd": "setpntr", "field": "ph_working_mode",
        "options": {"PROPORTIONAL": 0, "ON/OFF": 1},
    },
    "mv_working_mode": {
        "name": "Redox working mode", "icon": "mdi:swap-horizontal",
        "read_cmd": "setpntr", "field": "mv_working_mode",
        "options": {"PROPORTIONAL": 0, "ON/OFF": 1},
    },
    "priority": {
        "name": "Priority mode", "icon": "mdi:priority-high",
        "read_cmd": "paramtr", "field": "priority",
        "options": {"No priority": 1, "pH priority": 2, "Redox priority": 3},
    },
    "flow_mode": {
        "name": "Flow mode", "icon": "mdi:waves",
        "read_cmd": "flowstr", "field": "flow_mode",
        "options": {"Disable": 0, "Reverse": 1, "Direct": 2},
    },
    "probe_failure_ph_mode": {
        "name": "Probe failure pH mode", "icon": "mdi:alarm-check",
        "read_cmd": "allprbr", "field": "probe_failure_ph_mode",
        "options": {"DOSE": "0", "STOP": "1"},
    },
    "probe_failure_mv_mode": {
        "name": "Probe failure Redox mode", "icon": "mdi:alarm-check",
        "read_cmd": "allprbr", "field": "probe_failure_mv_mode",
        "options": {"DOSE": "0", "STOP": "1"},
    },
    "dosing_alarm_ph_mode": {
        "name": "Dosing alarm pH mode", "icon": "mdi:alarm",
        "read_cmd": "alldosr", "field": "dosing_alarm_ph_mode",
        "options": {"DOSE": "0", "STOP": "1"},
    },
    "dosing_alarm_mv_mode": {
        "name": "Dosing alarm Redox mode", "icon": "mdi:alarm",
        "read_cmd": "alldosr", "field": "dosing_alarm_mv_mode",
        "options": {"DOSE": "0", "STOP": "1"},
    },
}
