"""Position and maximum speed of each Axis, and the Session duration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import DEGREE, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CatWandConnectConfigEntry
from .api import AXES, AxisSettings, RobotState
from .entity import CatWandConnectEntity
from .live import RobotLive

PARALLEL_UPDATES = 0

# Before Calibration the robot keeps every Axis within this safe zone.
UNCALIBRATED_MIN = 60
UNCALIBRATED_MAX = 120
SPEED_UNIT = f"{DEGREE}/s"
# The lowest minimum speed the robot accepts, in °/s.
SLOWEST_SPEED = 1


@dataclass(frozen=True, kw_only=True)
class AxisNumberDescription(NumberEntityDescription):
    """A number reading one Axis."""

    axis: str
    value_fn: Callable[[RobotState, AxisSettings], float | None]
    set_fn: Callable[[RobotLive, str, float], Awaitable[None]]
    # Bounds from the axis settings, or None for the fixed native_min/max_value.
    bounds_fn: Callable[[bool, AxisSettings], tuple[float, float]] | None = None


def _travel(calibrated: bool, axis: AxisSettings) -> tuple[float, float]:
    if not calibrated:
        return UNCALIBRATED_MIN, UNCALIBRATED_MAX
    return axis.min, axis.max


def _horizontal(state: RobotState, _: AxisSettings) -> float | None:
    return state.h


def _vertical(state: RobotState, _: AxisSettings) -> float | None:
    return state.v


async def _set_position(live: RobotLive, axis: str, degrees: float) -> None:
    await live.client.position(axis, degrees)


async def _set_max_speed(live: RobotLive, axis: str, speed: float) -> None:
    changes: dict[str, float] = {"maxSpeed": speed}
    # Home Assistant knows only the maximum: like over MQTT, a maximum at or
    # below the minimum takes the minimum down to a tenth of it rather than
    # being refused (the robot validates the settings as a whole).
    current = live.settings.axes[axis] if live.settings else None
    if current is not None and current.min_speed >= speed:
        changes["minSpeed"] = max(SLOWEST_SPEED, speed / 10)
    live.apply_settings(await live.client.update_settings({"axes": {axis: changes}}))


def _descriptions(axis: str) -> list[AxisNumberDescription]:
    return [
        AxisNumberDescription(
            key=f"{axis}_position",
            translation_key=f"{axis}_position",
            axis=axis,
            native_unit_of_measurement=DEGREE,
            native_step=1,
            mode=NumberMode.SLIDER,
            value_fn=_horizontal if axis == "horizontal" else _vertical,
            set_fn=_set_position,
            bounds_fn=_travel,
        ),
        AxisNumberDescription(
            key=f"{axis}_max_speed",
            translation_key=f"{axis}_max_speed",
            axis=axis,
            native_unit_of_measurement=SPEED_UNIT,
            native_min_value=10,
            native_max_value=360,
            native_step=5,
            mode=NumberMode.BOX,
            value_fn=lambda _, settings: settings.max_speed,
            set_fn=_set_max_speed,
        ),
    ]


NUMBERS: tuple[AxisNumberDescription, ...] = tuple(
    description for axis in AXES for description in _descriptions(axis)
)

SESSION_DURATION = NumberEntityDescription(
    key="session_duration",
    translation_key="session_duration",
    native_unit_of_measurement=UnitOfTime.MINUTES,
    native_min_value=1,
    native_max_value=60,
    native_step=1,
    mode=NumberMode.BOX,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CatWandConnectConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the position, maximum speed and Session duration numbers."""
    live = entry.runtime_data
    async_add_entities(
        [
            *(AxisNumber(live, description) for description in NUMBERS),
            SessionDurationNumber(live, SESSION_DURATION),
        ]
    )


class AxisNumber(CatWandConnectEntity, NumberEntity):
    """One Axis's position or maximum speed."""

    entity_description: AxisNumberDescription

    @property
    def _axis(self) -> AxisSettings | None:
        settings = self.live.settings
        return settings.axes[self.entity_description.axis] if settings else None

    @property
    def native_value(self) -> float | None:
        """The value from the latest state and settings."""
        state, axis = self.live.state, self._axis
        if state is None or axis is None:
            return None
        return self.entity_description.value_fn(state, axis)

    def _bounds(self) -> tuple[float, float] | None:
        bounds_fn, settings = self.entity_description.bounds_fn, self.live.settings
        if bounds_fn is None or settings is None:
            return None
        state = self.live.state
        calibrated = state.calibrated if state else settings.calibrated
        return bounds_fn(calibrated, settings.axes[self.entity_description.axis])

    @property
    def native_min_value(self) -> float:
        """Lower bound: the axis's Travel limit for positions."""
        bounds = self._bounds()
        return bounds[0] if bounds else super().native_min_value

    @property
    def native_max_value(self) -> float:
        """Upper bound: the axis's Travel limit for positions."""
        bounds = self._bounds()
        return bounds[1] if bounds else super().native_max_value

    async def async_set_native_value(self, value: float) -> None:
        """Move the axis, or change its maximum speed."""
        description = self.entity_description
        await self._command(description.set_fn(self.live, description.axis, value))


class SessionDurationNumber(CatWandConnectEntity, NumberEntity):
    """How long a Play session lasts, in minutes."""

    @property
    def native_value(self) -> float | None:
        """The Session duration pushed on /ws, else the one last read."""
        state, settings = self.live.state, self.live.settings
        if state is not None and state.session_minutes is not None:
            return state.session_minutes
        return settings.session_minutes if settings else None

    async def async_set_native_value(self, value: float) -> None:
        """Change the Session duration (no PIN needed)."""
        await self._command(
            self.live.client.update_settings({"sessionMinutes": round(value)})
        )
