"""Play session event: each start, end, stop and refusal from the robot's journal.

Needs a firmware with the Play session journal; not created otherwise.
"""

from __future__ import annotations

from homeassistant.components.event import EventEntity, EventEntityDescription
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CatWandConnectConfigEntry
from .api import PLAY_EVENTS, JournalEvent
from .entity import CatWandConnectEntity

PARALLEL_UPDATES = 0

PLAY_SESSION = EventEntityDescription(
    key="play_session",
    translation_key="play_session",
    event_types=list(PLAY_EVENTS),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CatWandConnectConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the Play session event if the robot keeps a journal."""
    if entry.runtime_data.has_journal:
        async_add_entities([PlaySessionEvent(entry.runtime_data, PLAY_SESSION)])


class PlaySessionEvent(CatWandConnectEntity, EventEntity):
    """Fires with event type started, ended, stopped or refused.

    Attributes: `source` (device_interface, home_assistant_mqtt,
    home_assistant_native…) and `reason` (stop, stow, manual_control… for a
    stop; busy, not_calibrated… for a refusal; None otherwise).
    """

    _platform_domain = "event"

    async def async_added_to_hass(self) -> None:
        """Follow the robot's state and its journal events."""
        await super().async_added_to_hass()
        self.async_on_remove(self.live.async_add_event_listener(self._on_event))

    @callback
    def _on_event(self, event: JournalEvent) -> None:
        if event.what not in PLAY_EVENTS:
            return  # a type a later firmware may add
        self._trigger_event(event.what, {"source": event.source, "reason": event.reason})
        self.async_write_ha_state()
