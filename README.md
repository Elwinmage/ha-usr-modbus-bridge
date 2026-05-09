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

Home Assistant custom integration for **USR serial-to-ethernet converters** (USR-TCP232-304, USR-TCP232-306, USR-N510) operating in transparent TCP mode, bridging RS-485 Modbus devices.

---

## Supported devices

| Device | Manufacturer | Protocol | Baud | Address | Status |
|--------|-------------|----------|------|---------|--------|
| InverFlow Eco | Madimack / Aquagem | Modbus RTU 8N1 | 9600 | 0xAA (170) | ✅ Fully supported |

> The InverFlow Eco is an OEM version of the Aquagem InverPro pool pump. All variants sharing the same controller (Madimack, Aquagem, Fairland INVERX, etc.) should be compatible.

---

## Hardware setup

```
Home Assistant
     │
     │ TCP
     ▼
USR-TCP232-304          ← transparent TCP→RS485 bridge
192.168.0.x : 8899
9600 baud / 8N1
     │
     │ RS-485 (PIN6=A+  PIN7=B-)
     ▼
InverFlow Eco pump
Modbus addr 170 (0xAA)
```

### USR converter wiring

| InverFlow connector | USR terminal |
|---------------------|-------------|
| PIN 6 (RS485 A / DATA+) | A+ |
| PIN 7 (RS485 B / DATA−) | B− |
| PIN 5 (GND) | GND (optional) |

### USR-TCP232-304 configuration

| Parameter | Value |
|-----------|-------|
| Work Mode | **TCP Server** |
| Local Port | 8899 |
| Baud Rate | 9600 |
| Data Size | 8 bit |
| Parity | None |
| Stop Bits | 1 |
| Similar RFC2217 | **❌ OFF** |
| TCP Server-kick off old connection | **❌ OFF** |
| Modbus Type | None |
| Buffer Data Before Connected | ❌ OFF |

> ⚠️ **RFC2217 must be disabled.** When enabled, the USR receives TCP data but does not forward it to RS-485 (TX stays at 0 bytes).

---

## Installation

### HACS (recommended)

1. In HACS → Integrations → ⋮ → Custom repositories
2. Add `https://github.com/Elwinmage/ha-usr-modbus-bridge` as **Integration**
3. Install **USR Modbus Bridge**
4. Restart Home Assistant

### Manual

Copy `custom_components/usr_modbus_bridge/` into your HA `custom_components/` folder and restart.

---

## Configuration

1. **Settings → Devices & Services → Add Integration**
2. Search for **USR Modbus Bridge**

### Step 1 — Gateway

| Field | Description |
|-------|-------------|
| Gateway model | USR-TCP232-304 / USR-TCP232-306 / USR-N510 / Other |
| IP address | IP of the USR converter |
| TCP port | Default: 8899 |
| Baud rate | Must match converter setting (default: 9600) |
| Data bits | 8 |
| Parity | None |
| Stop bits | 1 |

### Step 2 — Device

| Field | Description |
|-------|-------------|
| Device type | Select from supported device profiles |
| Modbus address | Decimal — InverFlow default: **170** |
| Friendly name | Name shown in HA |
| Poll interval | How often to read registers (2–300 s, default 10 s) |

### Options (post-setup)

Click **Configure** on the integration entry to change baud rate, bus parameters, and poll interval without re-adding the integration. Changes trigger an automatic reload.

---

## Entities

### InverFlow Eco

| Entity | Type | Description |
|--------|------|-------------|
| `switch.*_power` | Switch | Turn pump ON (restores last speed) / OFF (setpoint=0) |
| `sensor.*_speed` | Sensor | Actual running speed % |
| `sensor.*_power` | Sensor | Instant power consumption W |
| `number.*_speed_setpoint` | Number | Target speed slider 0–100% |
| `button.*_restart_connection` | Button | Force TCP reconnect + wake-up ping |
| `sensor.*_error` | Sensor (diag) | Decoded error text from register 2001 |
| `sensor.*_firmware_const_*` | Sensor (diag) | Raw firmware constants (hidden by default) |

> Diagnostic entities are hidden by default. Enable them via **Entity → Settings → Visible**.

---

## Resilience

The integration handles several failure modes automatically:

| Situation | Behaviour |
|-----------|-----------|
| Pump RS-485 asleep after power cut | **Wake-up ping** sent at startup and after every reconnect (single read of register 0x07D1) |
| All registers return ERR for 3 consecutive polls | Automatic TCP reconnect + wake-up |
| No valid data received for 5 minutes | Automatic TCP reconnect + wake-up |
| Manual recovery needed | Press the **Restart connection** button |

> ⚠️ The USR converter only accepts **one TCP client at a time**. Do not run diagnostic scripts (socat, Python monitor) while the HA integration is active.

---

## InverFlow Eco — Modbus register map

> Confirmed by RS-485 capture session and Tuya/Modbus correlation (2026-05-08).

### Read registers (FC=03, device address 0xAA)

| Register (hex) | Register (dec) | Key | Description | Notes |
|----------------|----------------|-----|-------------|-------|
| 0x07D1 | 2001 | `error_code` | Error bitmask | 0 = no error. Also used as wake-up register |
| 0x07D2 | 2002 | `op_condition` | Operation condition bitmask | bit0=1 → running |
| 0x07D3 | 2003 | `speed_pct` | Running capacity % | Actual speed, not setpoint |
| 0x07D4 | 2004 | `power_w` | Instant power W | Confirmed vs Tuya DPS 5 |
| 0x07D7 | 2007 | `const_2007` | Firmware constant | Fixed value, meaning unknown |
| 0x07D8 | 2008 | `const_2008` | Firmware constant | Fixed value, meaning unknown |
| 0x07D9 | 2009 | `const_2009` | Firmware constant | Fixed value, meaning unknown |

### Write register (FC=06)

| Register (hex) | Register (dec) | Description | Range |
|----------------|----------------|-------------|-------|
| 0x0BB9 | 3001 | Speed setpoint % | 0 = stop, 30–100 = run |

> Speed is automatically snapped to the nearest 5% and clamped to 30% minimum when running.

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

The InverFlow Eco has **no dedicated ON/OFF Modbus register**. The integration implements it via the setpoint:

- `turn_off` → write 0 to register 0x0BB9
- `turn_on` → write last known speed (default 80%) to register 0x0BB9

The `switch` entity reads `op_condition` bit 0 for the actual running state.

### Wake-up behaviour

After a power cut or extended RS-485 silence, the pump stops responding to Modbus. A single FC=03 read on register **0x07D1** (error code) re-activates the RS-485 interface. This is sent automatically at startup and after every TCP reconnect.

---

## Adding new devices

1. Create `custom_components/usr_modbus_bridge/bridge/devices/mydevice.py`
2. Subclass `ModbusDevice` from `bridge/devices/base.py`
3. Declare `READ_REGISTERS`, implement `set_speed()`, set `WAKE_UP_REGISTER` if needed
4. Register the class in `const.py → DEVICE_PROFILES`

```python
# Example skeleton
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

### Pump does not respond after power cut
Press the **Restart connection** button. The wake-up ping will re-activate the RS-485 interface.

### TX counter stays at 0 on USR web interface
- Disable **Similar RFC2217** in the USR web interface → Save → power cycle the USR
- Disable **TCP Server-kick off old connection**

### All entities show unavailable
- Check that no other client (socat, Python script) is connected to port 8899
- Verify the USR is reachable: `nc -zv <USR_IP> 8899`
- Check HA logs for connection errors

### Integration does not find the device during setup
- Confirm the Modbus address in the pump menu (InverFlow Eco default: **170**)
- Ensure the pump is powered on and the RS-485 bus is wired correctly (PIN6=A+, PIN7=B−)

---

## Related projects

- [ha-usr-r16-component](https://github.com/Elwinmage/ha-usr-r16-component) — USR-R16 relay controller integration
- [ESPHome InverFlow config](https://forums.whirlpool.net.au/archive/3kpyw2n7) — community ESPHome YAML for the same pump

---

## License

MIT

---

## ESPHome alternative

If you prefer a direct ESP32 solution instead of the USR TCP bridge, you can use an ESP32 with a MAX485 module connected directly to the pump RS-485 bus.

### Hardware

<p align="center">
  <img src="doc/img/max485_module.png" alt="MAX485 module" width="500"/>
</p>

| Component | Example |
|-----------|---------|
| ESP32 dev board | ESP32-DevKitC or any ESP32 board |
| RS-485 transceiver | MAX485 module (C25B or equivalent) |

### Wiring

```
ESP32 GPIO14 (TX) ──→ MAX485 DI
ESP32 GPIO15 (RX) ←── MAX485 RO
ESP32 GPIO23      ──→ MAX485 RE  ┐ tie together
ESP32 GPIO23      ──→ MAX485 DE  ┘ (direction control)
MAX485 VCC        ←── 5V
MAX485 GND        ──── GND
MAX485 A (DATA+)  ──── InverFlow connector PIN 6
MAX485 B (DATA−)  ──── InverFlow connector PIN 7
```

> ⚠️ **RE and DE must be tied together** on the MAX485 module. When the ESP32 drives GPIO23 HIGH, the module transmits. When LOW, it receives.

### ESPHome configuration

The full YAML is available in [`doc/inverflow_esphome.yaml`](doc/inverflow_esphome.yaml).

Key features of the config:

- **Wake-up ping** at boot: reads register `0x07D1` to re-activate the pump RS-485 interface after power loss
- **Periodic wake-up** every 5 minutes via `interval:` to keep the bus alive
- **Manual wake-up button** in HA in case the pump stops responding
- **Speed setpoint** snapped to nearest 5%, minimum 30% when running
- **ON/OFF switch** — ON restores last speed, OFF writes 0 to setpoint
- **Hold-off** on switch to prevent UI flicker during Modbus write/read latency
- **Error decoder** — converts register 2001 bitmask to human-readable text
- **Setpoint persisted** across ESP32 reboots via `restore_value: true`

### Quick start

```bash
# Install ESPHome
pip install esphome

# Create secrets.yaml with your credentials
cat > secrets.yaml << 'SECRETS'
wifi_ssid: "YourSSID"
wifi_password: "YourPassword"
api_key: "your_32_byte_base64_api_key"
ota_password: "your_ota_password"
ap_password: "fallback_ap_password"
inverflow_ip: "192.168.0.x"
gateway: "192.168.0.1"
subnet: "255.255.255.0"
SECRETS

# Flash the ESP32
esphome run doc/inverflow_esphome.yaml
```

### Entities created by ESPHome

| Entity | Type | Description |
|--------|------|-------------|
| `switch.*_power` | Switch | ON/OFF (setpoint 0 / last speed) |
| `number.*_speed_setpoint` | Number | Target speed slider 30-100% step 5% |
| `sensor.*_speed` | Sensor | Actual running speed % |
| `sensor.*_power` | Sensor | Instant power W |
| `binary_sensor.*_running` | Binary sensor | Running state (op_condition bit 0) |
| `text_sensor.*_error` | Text sensor | Decoded error from register 2001 |
| `button.*_wake_up_rs485` | Button | Manual RS-485 wake-up ping |
