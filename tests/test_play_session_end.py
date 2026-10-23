"""Play session end: when the running Play session ends, from /ws `play.remaining`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from homeassistant.const import ATTR_DEVICE_CLASS, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .common import ACTIVITY, H_POSITION, PLAY_SESSION_END, set_up, state_of, until
from .fake_robot import FakeRobot

NOW = datetime(2026, 10, 23, 12, 0, 0, tzinfo=UTC)


class Clock:
    """Home Assistant's clock, moved by hand (the event loop keeps real time)."""

    def __init__(self) -> None:
        self.now = NOW

    def move_to(self, when: datetime) -> None:
        self.now = when


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    clock = Clock()
    monkeypatch.setattr(dt_util, "utcnow", lambda: clock.now)
    return clock


def end_of(hass: HomeAssistant) -> datetime | None:
    state = state_of(hass, PLAY_SESSION_END)
    if state in (None, STATE_UNKNOWN, STATE_UNAVAILABLE):
        return None
    return datetime.fromisoformat(state)


async def play(robot: FakeRobot, remaining: int) -> None:
    robot.activity = "playing"
    robot.play_remaining = remaining
    await robot.push_state()


async def test_unknown_while_no_session_runs(
    hass: HomeAssistant, robot: FakeRobot, entity_registry: er.EntityRegistry
) -> None:
    await set_up(hass, robot)

    state = hass.states.get(PLAY_SESSION_END)
    assert state.state == STATE_UNKNOWN
    assert state.attributes[ATTR_DEVICE_CLASS] == "timestamp"
    assert entity_registry.async_get(PLAY_SESSION_END).unique_id == (
        f"{robot.device_id}_play_session_end"
    )


async def test_shows_when_the_session_ends(
    hass: HomeAssistant, robot: FakeRobot, clock: Clock
) -> None:
    await set_up(hass, robot)

    await play(robot, 600)
    await until(lambda: end_of(hass) is not None)
    assert end_of(hass) == NOW + timedelta(seconds=600)


async def test_counting_down_keeps_the_end_still(
    hass: HomeAssistant, robot: FakeRobot, clock: Clock
) -> None:
    """Each pushed state reads the time left rounded up: no jitter in the end."""
    await set_up(hass, robot)
    await play(robot, 600)
    await until(lambda: end_of(hass) is not None)

    # 11.9 s in, a time left of 590 s (rounded up, read on the robot a moment
    # earlier) puts the end 1.9 s later: still the same end.
    clock.move_to(NOW + timedelta(seconds=11.9))
    robot.h = 70.0
    await play(robot, 590)
    await until(lambda: state_of(hass, H_POSITION) == "70.0")
    assert end_of(hass) == NOW + timedelta(seconds=600)


async def test_a_new_session_moves_the_end(
    hass: HomeAssistant, robot: FakeRobot, clock: Clock
) -> None:
    await set_up(hass, robot)
    await play(robot, 600)
    await until(lambda: end_of(hass) is not None)

    clock.move_to(NOW + timedelta(seconds=60))
    await play(robot, 900)
    await until(lambda: end_of(hass) == NOW + timedelta(seconds=960))


async def test_unknown_again_once_the_session_ends(
    hass: HomeAssistant, robot: FakeRobot
) -> None:
    await set_up(hass, robot)
    await play(robot, 600)
    await until(lambda: end_of(hass) is not None)

    await robot.set_activity("stowing")
    await until(lambda: state_of(hass, PLAY_SESSION_END) == STATE_UNKNOWN)


async def test_unavailable_while_the_robot_is_away(
    hass: HomeAssistant, robot: FakeRobot
) -> None:
    await set_up(hass, robot)
    await play(robot, 600)
    await until(lambda: end_of(hass) is not None)

    await robot.go_offline()
    await until(lambda: state_of(hass, PLAY_SESSION_END) == STATE_UNAVAILABLE)


async def test_older_firmware_without_the_time_left_reads_unknown(
    hass: HomeAssistant, robot: FakeRobot
) -> None:
    robot.sends_play = False
    await set_up(hass, robot)
    await play(robot, 600)
    await until(lambda: state_of(hass, ACTIVITY) == "playing")
    assert state_of(hass, PLAY_SESSION_END) == STATE_UNKNOWN
