# ha-usr-modbus-bridge

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)

Home Assistant custom integration for **USR serial-to-ethernet converters** (USR-TCP232-304, USR-TCP232-306, USR-N510) operating in transparent TCP mode, bridging RS-485 Modbus devices.

## Supported devices

| Device | Protocol | Status |
|--------|----------|--------|
| Madimack InverFlow Eco | Modbus RTU 9600 8N1 addr=0xAA | ✅ Supported |

## Installation

### HACS (recommended)
1. Add this repo as a custom repository in HACS
2. Install "USR Modbus Bridge"
3. Restart Home Assistant

### Manual
Copy `custom_components/usr_modbus_bridge/` to your HA `custom_components/` folder and restart.

## Configuration

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **USR Modbus Bridge**
3. **Step 1 — Gateway**: enter IP, port (default 8899), baud rate (default 9600)
4. **Step 2 — Device**: select device type, Modbus address, friendly name

## Hardware setup

```
Home Assistant ──TCP──▶ USR-TCP232-304 ──RS485──▶ InverFlow Eco
                         192.168.0.8:8899          addr=0xAA (170)
                         9600 baud 8N1             PIN6=A+ PIN7=B-
```

## Entities created (InverFlow Eco)

| Entity | Type | Description |
|--------|------|-------------|
| `switch.*_power` | Switch | ON (last speed) / OFF (setpoint=0) |
| `sensor.*_speed` | Sensor | Actual speed % |
| `number.*_speed_setpoint` | Number | Target speed 0-100% (slider) |
| `sensor.*_power` | Sensor | Instant power W |
| `sensor.*_motor_temperature` | Sensor | Motor temperature °C |
| `sensor.*_energy_today` | Sensor | Energy today Wh |
| `sensor.*_energy_total` | Sensor | Total energy counter |

## Adding new devices

Create `custom_components/usr_modbus_bridge/bridge/devices/mydevice.py`,
subclass `ModbusDevice`, and register it in `const.py → DEVICE_PROFILES`.

## Notes

- ON/OFF is implemented via setpoint: `turn_off` writes 0, `turn_on` restores last speed
- No dedicated ON/OFF Modbus register found on the InverFlow Eco
- Register map confirmed by Modbus/Tuya correlation session

## License

MIT
