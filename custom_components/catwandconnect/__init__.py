"""The CatWandConnect integration.

One device per robot; its entities follow the state the robot pushes on /ws.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import CannotConnect, CatWandConnectClient
from .const import DOMAIN, MANUFACTURER, MODEL
from .live import RobotLive

PLATFORMS: list[Platform] = [Platform.NUMBER, Platform.SENSOR]

type CatWandConnectConfigEntry = ConfigEntry[RobotLive]


async def async_setup_entry(hass: HomeAssistant, entry: CatWandConnectConfigEntry) -> bool:
    """Set up a robot from a config entry."""
    client = CatWandConnectClient(async_get_clientsession(hass), entry.data[CONF_HOST])
    try:
        info = await client.info()
    except CannotConnect as err:
        raise ConfigEntryNotReady(f"Robot at {client.host} unreachable") from err

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

    live = RobotLive(hass, entry, client, device_id)
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
