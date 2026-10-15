"""The CatWandConnect integration.

One device per robot; its entities follow the state the robot pushes on /ws.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import CannotConnect, CatWandConnectClient
from .const import (
    CONF_PIN,
    DOMAIN,
    MANUFACTURER,
    MIN_API_VERSION,
    MIN_FIRMWARE,
    MODEL,
    UPDATE_URL,
)
from .card import async_register_card
from .live import RobotLive
from .websocket import async_register as async_register_websocket

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.UPDATE,
]

type CatWandConnectConfigEntry = ConfigEntry[RobotLive]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up what all robots share: the joystick card and its commands."""
    async_register_websocket(hass)
    await async_register_card(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: CatWandConnectConfigEntry) -> bool:
    """Set up a robot from a config entry."""
    client = CatWandConnectClient(
        async_get_clientsession(hass),
        entry.data[CONF_HOST],
        entry.data.get(CONF_PIN, ""),
    )
    try:
        info = await client.info()
    except CannotConnect as err:
        raise ConfigEntryNotReady(f"Robot at {client.host} unreachable") from err

    issue_id = f"firmware_too_old_{entry.entry_id}"
    if info.api is None or info.api < MIN_API_VERSION:
        # Retrying can't help: the owner has to update the robot, then reload.
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key="firmware_too_old",
            translation_placeholders={
                "name": entry.title,
                "version": info.version or "?",
                "min_firmware": MIN_FIRMWARE,
                "update_url": UPDATE_URL,
            },
        )
        return False
    ir.async_delete_issue(hass, DOMAIN, issue_id)

    device_id = entry.unique_id or info.device_id or entry.entry_id
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, device_id)},
        name=info.name,
        manufacturer=MANUFACTURER,
        model=MODEL,
        hw_version=info.chip,
        sw_version=info.version,
        configuration_url=f"{client.url}/",
    )

    live = RobotLive(hass, entry, client, device_id, info)
    entry.runtime_data = live
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    live.start()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: CatWandConnectConfigEntry) -> bool:
    """Unload a config entry and close the robot's socket."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.stop()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: CatWandConnectConfigEntry) -> None:
    """Drop the entry's repair issue along with it."""
    ir.async_delete_issue(hass, DOMAIN, f"firmware_too_old_{entry.entry_id}")
