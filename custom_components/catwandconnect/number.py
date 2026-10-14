"""Position and maximum speed numbers of each Axis."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import DEGREE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CatWandConnectConfigEntry
from .api import AXES, AxisSettings, RobotState
from .const import DOMAIN
from .entity import CatWandConnectEntity

PARALLEL_UPDATES = 0

# Before Calibration the robot keeps every Axis within this safe zone.
UNCALIBRATED_MIN = 60
UNCALIBRATED_MAX = 120
SPEED_UNIT = f"{DEGREE}/s"


@dataclass(frozen=True, kw_only=True)
class AxisNumberDescription(NumberEntityDescription):
    """A number reading one Axis."""

    axis: str
    value_fn: Callable[[RobotState, AxisSettings], float | None]
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
        ),
    ]


NUMBERS: tuple[AxisNumberDescription, ...] = tuple(
    description for axis in AXES for description in _descriptions(axis)
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CatWandConnectConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the position and maximum speed numbers."""
    async_add_entities(
        AxisNumber(entry.runtime_data, description) for description in NUMBERS
    )


class AxisNumber(CatWandConnectEntity, NumberEntity):
    """A number showing one Axis's position or maximum speed."""

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
        """Changing these values from Home Assistant isn't supported yet."""
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="read_only"
        )
