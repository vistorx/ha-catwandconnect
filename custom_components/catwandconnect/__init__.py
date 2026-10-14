"""The CatWandConnect integration.

Registers one device per robot. Entities come with vistorx/CatWandConnect#159.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import CannotConnect, CatWandConnectClient
from .const import DOMAIN, MANUFACTURER, MODEL


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a robot from a config entry."""
    client = CatWandConnectClient(async_get_clientsession(hass), entry.data[CONF_HOST])
    try:
        info = await client.info()
    except CannotConnect as err:
        raise ConfigEntryNotReady(f"Robot at {client.host} unreachable") from err

    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.unique_id or info.device_id or entry.entry_id)},
        name=info.name,
        manufacturer=MANUFACTURER,
        model=MODEL,
        hw_version=info.chip,
        sw_version=info.version,
        configuration_url=f"{client.url}/",
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return True
