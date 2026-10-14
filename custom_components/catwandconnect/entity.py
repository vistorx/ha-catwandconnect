"""Base entity of a robot's live state."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity, EntityDescription

from .const import DOMAIN
from .live import RobotLive


class CatWandConnectEntity(Entity):
    """An entity fed by the robot's /ws state; unavailable while it is down."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, live: RobotLive, description: EntityDescription) -> None:
        self.live = live
        self.entity_description = description
        self._attr_unique_id = f"{live.device_id}_{description.key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, live.device_id)})

    @property
    def available(self) -> bool:
        """Available while the robot's socket is up."""
        return self.live.connected

    async def async_added_to_hass(self) -> None:
        """Follow the robot's state."""
        self.async_on_remove(self.live.async_add_listener(self.async_write_ha_state))
