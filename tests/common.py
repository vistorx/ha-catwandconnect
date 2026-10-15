"""Helpers shared by the entity tests."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from homeassistant.const import CONF_HOST, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.catwandconnect.const import CONF_PIN, DOMAIN

from .fake_robot import FakeRobot

ACTIVITY = "sensor.catwandconnect_activity"
H_POSITION = "number.catwandconnect_horizontal_position"
V_POSITION = "number.catwandconnect_vertical_position"
H_MAX_SPEED = "number.catwandconnect_horizontal_maximum_speed"
V_MAX_SPEED = "number.catwandconnect_vertical_maximum_speed"
PLAY_SESSION = "switch.catwandconnect_play_session"
SESSION_DURATION = "number.catwandconnect_session_duration"
STOW = "button.catwandconnect_stow"
FIRMWARE = "update.catwandconnect_firmware"


async def until(predicate: Callable[[], bool], timeout: float = 5) -> None:
    """Let the event loop run until `predicate` holds."""
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


def state_of(hass: HomeAssistant, entity_id: str) -> str | None:
    """The entity's state string, or None when it doesn't exist."""
    state = hass.states.get(entity_id)
    return state.state if state else None


async def set_up(
    hass: HomeAssistant, robot: FakeRobot, pin: str = ""
) -> MockConfigEntry:
    """Add the robot with `pin` stored, and wait for its live state."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=robot.device_id,
        data={CONF_HOST: robot.host, CONF_PIN: pin},
        title=robot.name,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await until(lambda: state_of(hass, ACTIVITY) not in (None, STATE_UNAVAILABLE))
    return entry
