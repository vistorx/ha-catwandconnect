"""Sensors: the robot's activity, when its Play session ends, and the Play sessions started today."""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

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

PLAY_SESSION_END = SensorEntityDescription(
    key="play_session_end",
    translation_key="play_session_end",
    device_class=SensorDeviceClass.TIMESTAMP,
)

# The robot's time left is rounded up to the second and read when a state is
# pushed: an end that moves less than this is the same end.
END_TOLERANCE = timedelta(seconds=2)

SESSIONS_TODAY = SensorEntityDescription(
    key="sessions_today",
    translation_key="sessions_today",
    # Back to 0 at the robot's local midnight: a reset, not a decrease.
    state_class=SensorStateClass.TOTAL_INCREASING,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CatWandConnectConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the Activity and Play session end sensors, and Sessions today if the robot keeps a journal."""
    live = entry.runtime_data
    entities: list[SensorEntity] = [
        ActivitySensor(live, ACTIVITY),
        PlaySessionEndSensor(live, PLAY_SESSION_END),
    ]
    if live.has_journal:
        entities.append(SessionsTodaySensor(live, SESSIONS_TODAY))
    async_add_entities(entities)


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


class PlaySessionEndSensor(CatWandConnectEntity, SensorEntity):
    """When the running Play session ends: Home Assistant's clock + /ws `play.remaining`.

    Unknown when no session runs, and with a firmware that doesn't send the
    time left. The end only moves when it changes by more than END_TOLERANCE,
    so counting down doesn't rewrite the state every second.
    """

    _platform_domain = "sensor"
    _end: datetime | None = None

    async def async_added_to_hass(self) -> None:
        """Follow the robot's state, working out the end first."""
        self._follow()
        self.async_on_remove(self.live.async_add_listener(self._on_change))

    @callback
    def _on_change(self) -> None:
        self._follow()
        self.async_write_ha_state()

    @callback
    def _follow(self) -> None:
        state = self.live.state
        remaining = state.play_remaining if state is not None else None
        if remaining is None or remaining <= 0:
            self._end = None
            return
        end = dt_util.utcnow() + timedelta(seconds=remaining)
        if self._end is None or abs(end - self._end) > END_TOLERANCE:
            self._end = end

    @property
    def native_value(self) -> datetime | None:
        """The end of the running Play session; None when none runs."""
        return self._end


class SessionsTodaySensor(CatWandConnectEntity, SensorEntity):
    """Play sessions started since the robot's local midnight.

    Unknown while the robot has no clock: it gets Home Assistant's time when
    the integration connects.
    """

    _platform_domain = "sensor"

    @property
    def native_value(self) -> int | None:
        """The count, or unknown."""
        state = self.live.state
        return state.sessions_today if state is not None else None
