# config_flow.py
from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_SCAN_INTERVAL
import aiohttp

from .const import DOMAIN, DEFAULT_PORT, CONF_HOST, CONF_PORT, CONF_SLAVE_ID, DEFAULT_SCAN_INTERVAL

STEP_USER_DATA_SCHEMA = vol.Schema({
    vol.Required(CONF_HOST): str,
    vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
    vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): int
})

_LOGGER = logging.getLogger(__name__)

async def validate_input(hass: HomeAssistant, data: dict) -> dict[str, str]:
    """Validate the user input allows us to connect."""
    http_session = aiohttp.ClientSession()

    async with (http_session.get(
            f"http://{data[CONF_HOST]}:{data[CONF_PORT]}/nodes?view=summary"
    ) as response):
        if response.status != 200:
            error = await response.text()
            await http_session.close()
            raise ConnectionError(f"请求失败，状态码: {response.status}，{error}")

        await http_session.close()
        return {
            "title": f"Ray {data[CONF_HOST]}"
        }

    await http_session.close()


@config_entries.HANDLERS.register(DOMAIN)
class RayClusterConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SELogic."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)

                # 检查是否已配置
                # await self.async_set_unique_id(user_input[CONF_HOST])
                # self._abort_if_unique_id_configured()

                return self.async_create_entry(title=info["title"], data=user_input)

            except ConnectionError:
                errors["base"] = "cannot_connect"
            except Exception as e:  # pylint: disable=broad-except
                _LOGGER.error("Unexcepted error %s: %s", e.__class__.__name__, e)
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors
        )
