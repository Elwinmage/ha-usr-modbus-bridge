"""Config flow: Step 1=gateway, Step 2=device. OptionsFlow for post-setup edits."""
from __future__ import annotations
import logging
from typing import Any
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.data_entry_flow import FlowResult
from .bridge.modbus_client import ModbusTCPClient, ModbusClientError
from .const import (BAUD_RATES, BYTE_SIZES, CONF_BAUD, CONF_BYTE_SIZE,
                    CONF_DEVICE_ADDRESS, CONF_DEVICE_KEY, CONF_GATEWAY_MODEL,
                    CONF_PARITY, CONF_SCAN_INTERVAL, CONF_STOP_BITS,
                    DEFAULT_BAUD, DEFAULT_BYTE_SIZE, DEFAULT_PARITY, DEFAULT_PORT,
                    DEFAULT_SCAN_INTERVAL, DEFAULT_STOP_BITS, DEVICE_PROFILES,
                    DOMAIN, GATEWAY_MODELS, PARITIES, STOP_BITS)

_LOGGER = logging.getLogger(__name__)


def _gw_schema(d: dict | None = None) -> vol.Schema:
    d = d or {}
    return vol.Schema({
        vol.Required(CONF_GATEWAY_MODEL, default=d.get(CONF_GATEWAY_MODEL, list(GATEWAY_MODELS)[0])): vol.In(GATEWAY_MODELS),
        vol.Required(CONF_HOST,          default=d.get(CONF_HOST, "")): str,
        vol.Required(CONF_PORT,          default=d.get(CONF_PORT, DEFAULT_PORT)): vol.All(int, vol.Range(min=1, max=65535)),
        vol.Required(CONF_BAUD,          default=d.get(CONF_BAUD, DEFAULT_BAUD)): vol.In(BAUD_RATES),
        vol.Required(CONF_BYTE_SIZE,     default=d.get(CONF_BYTE_SIZE, DEFAULT_BYTE_SIZE)): vol.In(BYTE_SIZES),
        vol.Required(CONF_PARITY,        default=d.get(CONF_PARITY, DEFAULT_PARITY)): vol.In(PARITIES),
        vol.Required(CONF_STOP_BITS,     default=d.get(CONF_STOP_BITS, DEFAULT_STOP_BITS)): vol.In(STOP_BITS),
    })


def _dev_schema(d: dict | None = None) -> vol.Schema:
    d = d or {}
    return vol.Schema({
        vol.Required(CONF_DEVICE_KEY,     default=d.get(CONF_DEVICE_KEY, list(DEVICE_PROFILES)[0])): vol.In({k: v.DEVICE_NAME for k, v in DEVICE_PROFILES.items()}),
        vol.Required(CONF_DEVICE_ADDRESS, default=d.get(CONF_DEVICE_ADDRESS, 0xAA)): vol.All(int, vol.Range(min=1, max=254)),
        vol.Required(CONF_NAME,           default=d.get(CONF_NAME, "")): str,
        vol.Required(CONF_SCAN_INTERVAL,  default=d.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)): vol.All(int, vol.Range(min=2, max=300)),
    })


def _opt_schema(current: dict) -> vol.Schema:
    return vol.Schema({
        vol.Required(CONF_SCAN_INTERVAL, default=current.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)): vol.All(int, vol.Range(min=2, max=300)),
        vol.Required(CONF_BAUD,          default=current.get(CONF_BAUD, DEFAULT_BAUD)): vol.In(BAUD_RATES),
        vol.Required(CONF_BYTE_SIZE,     default=current.get(CONF_BYTE_SIZE, DEFAULT_BYTE_SIZE)): vol.In(BYTE_SIZES),
        vol.Required(CONF_PARITY,        default=current.get(CONF_PARITY, DEFAULT_PARITY)): vol.In(PARITIES),
        vol.Required(CONF_STOP_BITS,     default=current.get(CONF_STOP_BITS, DEFAULT_STOP_BITS)): vol.In(STOP_BITS),
    })


class UsrModbusBridgeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._gateway_data: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                c = ModbusTCPClient(host=user_input[CONF_HOST], port=user_input[CONF_PORT])
                await c.connect(); await c.disconnect()
            except ModbusClientError:
                errors["base"] = "cannot_connect"
            except Exception:
                errors["base"] = "unknown"
            if not errors:
                self._gateway_data = user_input
                return await self.async_step_device()
        return self.async_show_form(step_id="user", data_schema=_gw_schema(user_input), errors=errors)

    async def async_step_device(self, user_input: dict | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            device_key = user_input[CONF_DEVICE_KEY]
            address    = user_input[CONF_DEVICE_ADDRESS]
            name       = user_input[CONF_NAME].strip() or DEVICE_PROFILES[device_key].DEVICE_NAME
            unique_id  = f"{self._gateway_data[CONF_HOST]}:{self._gateway_data[CONF_PORT]}:{address:02X}"
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()
            profile = DEVICE_PROFILES[device_key]()
            profile.MODBUS_ADDRESS = address
            try:
                c = ModbusTCPClient(host=self._gateway_data[CONF_HOST], port=self._gateway_data[CONF_PORT])
                await c.connect()
                val = await c.read_register(address, profile.READ_REGISTERS[0].address)
                await c.disconnect()
                if val is None:
                    errors["base"] = "device_not_found"
            except ModbusClientError:
                errors["base"] = "cannot_connect"
            except Exception:
                errors["base"] = "unknown"
            if not errors:
                return self.async_create_entry(title=name, data={
                    **self._gateway_data,
                    CONF_DEVICE_KEY: device_key,
                    CONF_DEVICE_ADDRESS: address,
                    CONF_NAME: name,
                    CONF_SCAN_INTERVAL: user_input[CONF_SCAN_INTERVAL],
                })
        return self.async_show_form(step_id="device", data_schema=_dev_schema(user_input), errors=errors)

    @staticmethod
    def async_get_options_flow(config_entry):
        return UsrModbusBridgeOptionsFlow(config_entry)


class UsrModbusBridgeOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(self, user_input: dict | None = None) -> FlowResult:
        current = {**self._config_entry.data, **self._config_entry.options}
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(step_id="init", data_schema=_opt_schema(current))
