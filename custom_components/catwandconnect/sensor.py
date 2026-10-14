"""Activity sensor: what the robot is doing."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CatWandConnectConfigEntry
from .api import ACTIVITIES
from .entity import CatWandConnectEntity

PARALLEL_UPDATES = 0

ACTIVITY = SensorEntityDescription(
    key="activity",
    translation_key="activity",
    device_class=SensorDeviceClass.ENUM,
    options=list(ACTIVITIES),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CatWandConnectConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the Activity sensor."""
    async_add_entities([ActivitySensor(entry.runtime_data, ACTIVITY)])


class ActivitySensor(CatWandConnectEntity, SensorEntity):
    """The robot's activity, as pushed on /ws."""

    _platform_domain = "sensor"

    @property
    def native_value(self) -> str | None:
        """The activity; unknown for one this integration doesn't know."""
        state = self.live.state
        if state is None or state.activity not in ACTIVITIES:
            return None
        return state.activity
