"""Config flow — Step 1: gateway, Step 2: device."""
from __future__ import annotations
import logging
from typing import Any
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.data_entry_flow import FlowResult
from .bridge.modbus_client import ModbusTCPClient, ModbusClientError
from .const import (CONF_BAUD, CONF_DEVICE_ADDRESS, CONF_DEVICE_KEY,
                    CONF_GATEWAY_MODEL, DEFAULT_BAUD, DEFAULT_PORT,
                    DEVICE_PROFILES, DOMAIN, GATEWAY_MODELS)

_LOGGER = logging.getLogger(__name__)


class UsrModbusBridgeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._gateway_data: dict[str, Any] = {}

    async def async_step_user(self, user_input=None) -> FlowResult:
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
        schema = vol.Schema({
            vol.Required(CONF_GATEWAY_MODEL, default=(user_input or {}).get(CONF_GATEWAY_MODEL, list(GATEWAY_MODELS)[0])): vol.In(GATEWAY_MODELS),
            vol.Required(CONF_HOST,          default=(user_input or {}).get(CONF_HOST, "")): str,
            vol.Required(CONF_PORT,          default=(user_input or {}).get(CONF_PORT, DEFAULT_PORT)): vol.All(int, vol.Range(min=1, max=65535)),
            vol.Required(CONF_BAUD,          default=(user_input or {}).get(CONF_BAUD, DEFAULT_BAUD)): vol.In([1200, 2400, 4800, 9600, 19200, 38400]),
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_device(self, user_input=None) -> FlowResult:
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
                })
        schema = vol.Schema({
            vol.Required(CONF_DEVICE_KEY,     default=(user_input or {}).get(CONF_DEVICE_KEY, list(DEVICE_PROFILES)[0])): vol.In({k: v.DEVICE_NAME for k, v in DEVICE_PROFILES.items()}),
            vol.Required(CONF_DEVICE_ADDRESS, default=(user_input or {}).get(CONF_DEVICE_ADDRESS, 0xAA)): vol.All(int, vol.Range(min=1, max=254)),
            vol.Required(CONF_NAME,           default=(user_input or {}).get(CONF_NAME, "")): str,
        })
        return self.async_show_form(step_id="device", data_schema=schema, errors=errors)
