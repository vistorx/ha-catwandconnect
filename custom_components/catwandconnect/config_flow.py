"""Config flow for CatWandConnect.

Placeholder: the real flow (discovery, host, PIN, firmware check) comes with
vistorx/CatWandConnect#158. Until then every path aborts with not_implemented.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .const import DOMAIN


class CatWandConnectConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for CatWandConnect."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the robot's host."""
        if user_input is not None:
            return self.async_abort(reason="not_implemented")
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_HOST): str}),
        )

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """Handle a robot found by zeroconf."""
        return self.async_abort(reason="not_implemented")
