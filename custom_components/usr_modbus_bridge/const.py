"""Constants for usr_modbus_bridge."""
from __future__ import annotations
from .bridge.devices.inverflow import InverFlowEco
from .bridge.devices.hayward import HaywardHeatPump
from .bridge.devices.emec_wdphrh import EmecWdphrh

DOMAIN = "usr_modbus_bridge"

CONF_GATEWAY_MODEL  = "gateway_model"
CONF_BAUD           = "baud"
CONF_STOP_BITS      = "stop_bits"
CONF_PARITY         = "parity"
CONF_BYTE_SIZE      = "byte_size"
CONF_DEVICE_KEY     = "device_key"
CONF_DEVICE_ADDRESS = "device_address"
CONF_SCAN_INTERVAL  = "scan_interval"
CONF_REPLY_DELAY    = "reply_delay"   # ms; hold-off before answering a poll

DEFAULT_PORT          = 8899
DEFAULT_BAUD          = 9600
DEFAULT_STOP_BITS     = 1
DEFAULT_PARITY        = "none"
DEFAULT_BYTE_SIZE     = 8
DEFAULT_SCAN_INTERVAL = 10
DEFAULT_REPLY_DELAY   = 60             # ms (touch panel answers at ~77 ms)

BAUD_RATES = [1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200]
STOP_BITS  = {1: "1", 2: "2"}
PARITIES   = {"none": "None", "even": "Even", "odd": "Odd"}
BYTE_SIZES = {7: "7", 8: "8"}

GATEWAY_MODELS: dict[str, str] = {
    "USR-TCP232-304": "USR-TCP232-304",
    "USR-TCP232-306": "USR-TCP232-306",
    "USR-N510":       "USR-N510",
    "Other":          "Other (transparent TCP→RS485)",
}

DEVICE_PROFILES: dict[str, type] = {
    InverFlowEco.DEVICE_KEY:      InverFlowEco,
    HaywardHeatPump.DEVICE_KEY:   HaywardHeatPump,
    EmecWdphrh.DEVICE_KEY:        EmecWdphrh,
}

COORDINATOR     = "coordinator"
LISTENER        = "listener"
PLATFORMS_KEY   = "platforms"
SERVICE_RESTART = "restart"
