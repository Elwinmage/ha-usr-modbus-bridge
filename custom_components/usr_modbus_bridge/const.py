"""Constants for usr_modbus_bridge."""
from __future__ import annotations
from .bridge.devices.inverflow import InverFlowEco

DOMAIN = "usr_modbus_bridge"

CONF_GATEWAY_MODEL  = "gateway_model"
CONF_BAUD           = "baud"
CONF_DEVICE_KEY     = "device_key"
CONF_DEVICE_ADDRESS = "device_address"

DEFAULT_PORT = 8899
DEFAULT_BAUD = 9600

GATEWAY_MODELS: dict[str, str] = {
    "USR-TCP232-304": "USR-TCP232-304",
    "USR-TCP232-306": "USR-TCP232-306",
    "USR-N510":       "USR-N510",
    "Other":          "Other (transparent TCP→RS485)",
}

DEVICE_PROFILES: dict[str, type] = {
    InverFlowEco.DEVICE_KEY: InverFlowEco,
}

COORDINATOR = "coordinator"
