"""Stow button: puts the wand away."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CatWandConnectConfigEntry
from .entity import CatWandConnectEntity

PARALLEL_UPDATES = 0

STOW = ButtonEntityDescription(key="stow", translation_key="stow")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CatWandConnectConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the Stow button."""
    async_add_entities([StowButton(entry.runtime_data, STOW)])


class StowButton(CatWandConnectEntity, ButtonEntity):
    """Stows the wand: stops everything else and releases the servos."""

    _platform_domain = "button"

    async def async_press(self) -> None:
        """Stow."""
        await self._command(self.live.client.stow())
