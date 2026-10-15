"""Config flow for CatWandConnect: add a robot found by zeroconf or by host."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from ipaddress import IPv6Address
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .api import CannotConnect, CatWandConnectClient, LockedOut, RobotInfo, WrongPin
from .const import CONF_PIN, DOMAIN, MIN_API_VERSION, MIN_FIRMWARE, UPDATE_URL

USER_SCHEMA = vol.Schema({vol.Required(CONF_HOST): str})
PIN_SCHEMA = vol.Schema({vol.Required(CONF_PIN): str})
TOO_OLD_PLACEHOLDERS = {"min_firmware": MIN_FIRMWARE, "update_url": UPDATE_URL}

_LOGGER = logging.getLogger(__name__)


def _supported(api: int | None) -> bool:
    return api is not None and api >= MIN_API_VERSION


class CatWandConnectConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for CatWandConnect."""

    VERSION = 1

    _host: str
    _name: str
    _client: CatWandConnectClient
    _info: RobotInfo

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the robot's IP address or .local name."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._host = user_input[CONF_HOST].strip()
            try:
                return await self._async_add_robot()
            except CannotConnect:
                errors["base"] = "cannot_connect"
        return self.async_show_form(
            step_id="user", data_schema=USER_SCHEMA, errors=errors
        )

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """Handle a robot announcing _catwandconnect._tcp."""
        txt = discovery_info.properties
        address = discovery_info.ip_address
        host = f"[{address}]" if isinstance(address, IPv6Address) else str(address)
        if discovery_info.port not in (None, 80):
            host = f"{host}:{discovery_info.port}"
        self._host = host
        self._name = txt.get("name") or "CatWandConnect"
        # One line per announcement, so an owner who turns on debug logging can
        # tell "never heard" (network) from "heard and skipped" (vistorx/CatWandConnect#175).
        _LOGGER.debug(
            "Robot %s announced at %s (api %s, firmware %s)",
            txt.get("id"),
            host,
            txt.get("api"),
            txt.get("version"),
        )

        await self.async_set_unique_id(txt.get("id"))
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})
        try:
            api: int | None = int(txt.get("api", ""))
        except ValueError:
            api = None
        if not _supported(api):
            return self.async_abort(
                reason="firmware_too_old", description_placeholders=TOO_OLD_PLACEHOLDERS
            )
        self.context["title_placeholders"] = {"name": self._name}
        return await self.async_step_zeroconf_confirm()

    async def async_step_zeroconf_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the owner confirm the discovered robot."""
        if user_input is not None:
            try:
                return await self._async_add_robot()
            except CannotConnect:
                return self.async_abort(reason="cannot_connect")
        self._set_confirm_only()
        return self.async_show_form(
            step_id="zeroconf_confirm", description_placeholders={"name": self._name}
        )

    async def async_step_pin(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the Settings PIN (only when the robot has one)."""
        errors: dict[str, str] = {}
        placeholders = {"name": self._info.name}
        if user_input is not None:
            pin = user_input[CONF_PIN]
            try:
                await self._client.unlock(pin)
            except WrongPin:
                errors["base"] = "wrong_pin"
            except LockedOut as err:
                errors["base"] = "locked_out"
                placeholders["retry_after"] = str(err.retry_after)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            else:
                return self._async_create(pin)
        return self.async_show_form(
            step_id="pin",
            data_schema=PIN_SCHEMA,
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """The stored Settings PIN was refused: ask for the new one."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the robot's new Settings PIN and keep it once it unlocks."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        placeholders = {"name": entry.title}
        if user_input is not None:
            pin = user_input[CONF_PIN]
            client = CatWandConnectClient(
                async_get_clientsession(self.hass), entry.data[CONF_HOST]
            )
            try:
                await client.unlock(pin)
            except WrongPin:
                errors["base"] = "wrong_pin"
            except LockedOut as err:
                errors["base"] = "locked_out"
                placeholders["retry_after"] = str(err.retry_after)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PIN: pin}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=PIN_SCHEMA,
            errors=errors,
            description_placeholders=placeholders,
        )

    async def _async_add_robot(self) -> ConfigFlowResult:
        """Read the robot, refuse old firmware, then ask the PIN if one is set."""
        self._client = CatWandConnectClient(
            async_get_clientsession(self.hass), self._host
        )
        self._info = await self._client.info()
        if not _supported(self._info.api):
            return self.async_abort(
                reason="firmware_too_old", description_placeholders=TOO_OLD_PLACEHOLDERS
            )
        await self.async_set_unique_id(self._info.device_id, raise_on_progress=False)
        self._abort_if_unique_id_configured(updates={CONF_HOST: self._host})
        if (await self._client.auth()).enabled:
            return await self.async_step_pin()
        return self._async_create("")

    def _async_create(self, pin: str) -> ConfigFlowResult:
        return self.async_create_entry(
            title=self._info.name, data={CONF_HOST: self._host, CONF_PIN: pin}
        )
