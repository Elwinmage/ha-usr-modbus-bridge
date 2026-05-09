# ha-usr-modbus-bridge

<p align="center">
  <img src="custom_components/usr_modbus_bridge/brand/logo.png" alt="USR Modbus Bridge logo" width="200"/>
</p>

<p align="center">
  <img src="doc/img/card.png" alt="USR Modbus Bridge card" width="600"/>
</p>

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![IoT Class](https://img.shields.io/badge/IoT%20Class-Local%20Polling-green?style=flat-square)](https://developers.home-assistant.io/docs/architecture_index/)
[![GH-release](https://img.shields.io/github/v/release/Elwinmage/ha-usr-modbus-bridge.svg?style=flat-square)](https://github.com/Elwinmage/ha-usr-modbus-bridge/releases)
[![BuyMeCoffee](https://img.shields.io/badge/buy%20me%20a%20coffee-donate-yellow.svg?style=flat-square)](https://paypal.me/Elwinmage)

---

Home Assistant integration for **Modbus RS-485 pool pumps**, with two hardware approaches to connect your pump to Home Assistant — choose the one that fits your setup.

---

## Table of contents

- [Supported devices](#supported-devices)
- [Two ways to connect](#two-ways-to-connect)
  - [Option A — USR TCP bridge](#option-a--usr-tcp-bridge-recommended-for-most-users)
  - [Option B — ESP32 + MAX485](#option-b--esp32--max485-esphome)
  - [Comparison](#comparison)
- [InverFlow Eco — Modbus register map](#inverflow-eco--modbus-register-map)
- [HA integration setup (Option A)](#ha-integration-setup-option-a)
- [ESPHome setup (Option B)](#esphome-setup-option-b)
- [Entities](#entities)
- [Resilience & wake-up mechanism](#resilience--wake-up-mechanism)
- [Adding new devices](#adding-new-devices)
- [Troubleshooting](#troubleshooting)
- [Related projects](#related-projects)

---

## Supported devices

| Device | Manufacturer | Protocol | Baud | Address | Status |
|--------|-------------|----------|------|---------|--------|
| InverFlow Eco | Madimack / Aquagem | Modbus RTU 8N1 | 9600 | 0xAA (170) | ✅ Fully supported |

> The InverFlow Eco is an OEM version of the Aquagem InverPro pool pump. All variants sharing the same controller (Madimack, Aquagem, Fairland INVERX, etc.) should be compatible.

---

## Two ways to connect

Both options give you the same Home Assistant entities and the same local, cloud-free control. The difference is in the hardware between your pump and Home Assistant.

### Option A — USR TCP bridge *(recommended for most users)*

A **USR-TCP232-304** (or compatible) converter sits on the RS-485 bus and bridges it to your home network over TCP. The HA integration connects to it directly — no additional hardware required beyond the converter.

```
Home Assistant
     │
     │ TCP  (LAN)
     ▼
USR-TCP232-304
192.168.0.x:8899
9600 baud / 8N1
     │
     │ RS-485
     ▼
InverFlow Eco
addr 170 (0xAA)
```

**Pros:** simple setup, no firmware to maintain, one device for multiple pumps on the same bus.
**Cons:** requires a separate Ethernet/WiFi device on the network.

---

### Option B — ESP32 + MAX485 *(ESPHome)*

An **ESP32** with a cheap **MAX485 TTL module** connects directly to the pump RS-485 bus over GPIO. ESPHome handles the Modbus protocol and exposes entities to Home Assistant via the native API.

```
Home Assistant
     │
     │ ESPHome native API  (WiFi)
     ▼
ESP32 + MAX485 module
GPIO14=TX  GPIO15=RX  GPIO23=DE/RE
     │
     │ RS-485
     ▼
InverFlow Eco
addr 170 (0xAA)
```

**Pros:** ~5€ total hardware cost, no extra device on the network, fully local.
**Cons:** one ESP32 per RS-485 bus segment, requires flashing ESPHome firmware.

---

### Comparison

| | Option A — USR TCP bridge | Option B — ESP32 + MAX485 |
|---|---|---|
| **Hardware cost** | ~25-40€ | ~5-10€ |
| **Setup complexity** | Low — web UI config | Medium — ESPHome flash |
| **Multiple devices on same bus** | ✅ Yes | ⚠️ One bus per ESP32 |
| **Firmware to maintain** | ❌ None | ✅ ESPHome OTA |
| **HA integration** | Custom component (this repo) | ESPHome native API |
| **Network dependency** | TCP over LAN | WiFi |
| **Wake-up mechanism** | Automatic (coordinator) | Boot + 5min interval + button |

---

## InverFlow Eco — Modbus register map

> Confirmed by RS-485 capture session and Tuya/Modbus correlation (2026-05-08).

### Read registers (FC=03, device address 0xAA / 170)

| Register (hex) | Register (dec) | Key | Description | Notes |
|----------------|----------------|-----|-------------|-------|
| 0x07D1 | 2001 | `error_code` | Error bitmask | 0=no error — also the **wake-up register** |
| 0x07D2 | 2002 | `op_condition` | Operation condition bitmask | bit0=1 → running |
| 0x07D3 | 2003 | `speed_pct` | Running capacity % | Actual speed, not setpoint |
| 0x07D4 | 2004 | `power_w` | Instant power W | Confirmed vs Tuya DPS 5 |
| 0x07D7 | 2007 | `const_2007` | Firmware constant (~88) | Fixed value, meaning unknown |
| 0x07D8 | 2008 | `const_2008` | Firmware constant (~20) | Fixed value, meaning unknown |
| 0x07D9 | 2009 | `const_2009` | Firmware constant (~28) | Fixed value, meaning unknown |

### Write register (FC=06)

| Register (hex) | Register (dec) | Description | Range |
|----------------|----------------|-------------|-------|
| 0x0BB9 | 3001 | Speed setpoint % | 0=stop, 30–100=run |

> Speed is snapped to the nearest 5% and clamped to 30% minimum when running.

### Error bitmask (register 2001)

| Bit | Error |
|-----|-------|
| 0 | DC voltage abnormal |
| 1 | AC current sampling circuit failure |
| 2 | Phase-deficient protection |
| 3 | Master drive error |
| 4 | Heatsink sensor error |
| 5 | Heatsink overheat |
| 6 | Output current exceeds limit |
| 7 | Input voltage abnormal |
| 8 | No water protection |
| 9 | Panel↔master comm failure |
| 10 | Panel EEPROM read error |
| 11 | RTC read error |
| 12 | Main EEPROM read error |
| 13 | Motor current detection error |
| 14 | Motor power overload |
| 15 | PFC protection |

### ON/OFF strategy

The InverFlow Eco has **no dedicated ON/OFF Modbus register**:

- `turn_off` → write **0** to register 0x0BB9
- `turn_on` → write **last known speed** (default 80%) to register 0x0BB9

Running state is determined by reading `op_condition` bit 0.

### Wake-up behaviour

After a power cut or extended RS-485 silence, the pump stops responding. A single FC=03 read on register **0x07D1** re-activates the RS-485 interface. Both solutions implement this automatically.

---

## HA integration setup (Option A)

### USR converter configuration

| Parameter | Value |
|-----------|-------|
| Work Mode | **TCP Server** |
| Local Port | 8899 |
| Baud Rate | 9600 |
| Data Size | 8 bit |
| Parity | None |
| Stop Bits | 1 |
| **Similar RFC2217** | **❌ OFF** (critical — TX stays 0 if enabled) |
| **TCP Server-kick off old connection** | **❌ OFF** |
| Modbus Type | None |

### Wiring

| InverFlow connector | USR terminal |
|---------------------|-------------|
| PIN 6 (RS485 A / DATA+) | A+ |
| PIN 7 (RS485 B / DATA−) | B− |
| PIN 5 (GND) | GND (optional) |

### Installation

#### HACS (recommended)
1. HACS → Integrations → ⋮ → Custom repositories
2. Add `https://github.com/Elwinmage/ha-usr-modbus-bridge` as **Integration**
3. Install **USR Modbus Bridge** → Restart HA

#### Manual
Copy `custom_components/usr_modbus_bridge/` into your HA `custom_components/` folder and restart.

### Configuration

**Settings → Devices & Services → Add Integration → USR Modbus Bridge**

**Step 1 — Gateway**

| Field | Description |
|-------|-------------|
| Gateway model | USR-TCP232-304 / USR-TCP232-306 / USR-N510 / Other |
| IP address | IP of the USR converter |
| TCP port | Default: 8899 |
| Baud rate | 9600 |
| Data bits / Parity / Stop bits | 8 / None / 1 |

**Step 2 — Device**

| Field | Description |
|-------|-------------|
| Device type | InverFlow Eco |
| Modbus address | **170** (shown in pump menu) |
| Friendly name | e.g. "Pool pump" |
| Poll interval | 2–300 s (default 10 s) |

**Options (post-setup):** click **Configure** to change baud rate, bus parameters, or poll interval without re-adding the integration.

---

## ESPHome setup (Option B)

### Hardware

<p align="center">
  <img src="doc/img/max485_module.png" alt="MAX485 module" width="500"/>
</p>

| Component | Notes |
|-----------|-------|
| ESP32 dev board | Any ESP32 board |
| MAX485 module | C25B or equivalent (~2€) |

### Wiring

```
ESP32 GPIO14 (TX) ──→ MAX485 DI
ESP32 GPIO15 (RX) ←── MAX485 RO
ESP32 GPIO23      ──→ MAX485 RE  ┐ tie together
ESP32 GPIO23      ──→ MAX485 DE  ┘
MAX485 VCC        ←── 5V
MAX485 GND        ──── GND
MAX485 A (DATA+)  ──── InverFlow PIN 6
MAX485 B (DATA−)  ──── InverFlow PIN 7
```

> RE and DE are tied together on the module — GPIO23 HIGH = transmit, LOW = receive.

### Configuration

Full YAML: [`doc/inverflow_esphome.yaml`](doc/inverflow_esphome.yaml)

```bash
# Flash
esphome run doc/inverflow_esphome.yaml
```

---

## Entities

Both options expose equivalent entities:

| Entity | Type | Description |
|--------|------|-------------|
| Power | Switch | ON (restores last speed) / OFF (setpoint=0) |
| Speed | Sensor | Actual running speed % |
| Power | Sensor | Instant power consumption W |
| Speed setpoint | Number | Target speed slider |
| Restart / Wake-up | Button | Force reconnect + RS-485 wake-up |
| Error | Text sensor (diag) | Decoded error bitmask from reg 2001 |
| Firmware constants | Sensors (diag) | Raw firmware constants, hidden by default |

---

## Resilience & wake-up mechanism

| Situation | Option A (HA integration) | Option B (ESPHome) |
|-----------|--------------------------|-------------------|
| Pump asleep after power cut | Wake-up ping at startup + after every reconnect | Wake-up ping at boot |
| All registers ERR × 3 polls | Auto TCP reconnect + wake-up | ESPHome Modbus retry |
| No valid data for 5 min | Auto TCP reconnect + wake-up | Periodic wake-up every 5 min |
| Manual recovery | **Restart connection** button | **Wake-up RS485** button |

> ⚠️ Only **one TCP client** can connect to the USR converter at a time. Never run diagnostic scripts (socat, Python monitor) while the HA integration is active.

---

## Adding new devices

1. Create `custom_components/usr_modbus_bridge/bridge/devices/mydevice.py`
2. Subclass `ModbusDevice` from `bridge/devices/base.py`
3. Declare `READ_REGISTERS`, implement `set_speed()`, set `WAKE_UP_REGISTER` if needed
4. Register in `const.py → DEVICE_PROFILES`

```python
from .base import ModbusDevice, RegisterDef

class MyDevice(ModbusDevice):
    DEVICE_KEY       = "my_device"
    DEVICE_NAME      = "My Pool Pump"
    MODBUS_ADDRESS   = 0x01
    WAKE_UP_REGISTER = 0x0001  # optional

    READ_REGISTERS = [
        RegisterDef(0x0001, "speed", "Speed", "%", 1, 0),
        RegisterDef(0x0002, "power", "Power", "W", 1, 0),
    ]

    async def set_speed(self, client, speed_pct: int) -> bool:
        return await client.write_register(self.MODBUS_ADDRESS, 0x0010, speed_pct)

    @property
    def sensor_keys(self): return ["speed", "power"]

    @property
    def switch_key(self): return "speed"
```

---

## Troubleshooting

**Pump does not respond after power cut**
→ Press **Restart connection** (Option A) or **Wake-up RS485** (Option B). The wake-up ping re-activates the RS-485 interface.

**TX counter stays at 0 on USR web interface**
→ Disable **Similar RFC2217** in the USR web UI → Save → power cycle the USR physically.

**All entities show unavailable**
→ Verify no other client (socat, Python script) is connected to port 8899. Check HA logs for connection errors.

**Integration does not find the device during setup**
→ Confirm Modbus address in pump menu (InverFlow Eco default: **170**). Ensure pump is powered and PIN6/PIN7 wired correctly.

**ESPHome: pump not responding after ESP32 reboot**
→ The boot wake-up ping handles this automatically. If it persists, press the **Wake-up RS485** button in HA.

---

## Related projects

- [ha-usr-r16-component](https://github.com/Elwinmage/ha-usr-r16-component) — USR-R16 relay controller integration
- [ESPHome InverFlow community config](https://forums.whirlpool.net.au/archive/3kpyw2n7) — original ESPHome YAML inspiration

---

## License

MIT
