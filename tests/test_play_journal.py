"""Play session journal: the event entity, Sessions today and the Robot clock.

vistorx/CatWandConnect#239. The robot records each Play session event and
pushes it on /ws; the integration tells the robot it is Home Assistant (so the
journal credits its commands) and gives it Home Assistant's time on connect.
"""

from __future__ import annotations

import time

import pytest
from homeassistant.components.event import ATTR_EVENT_TYPE, ATTR_EVENT_TYPES
from homeassistant.components.sensor import ATTR_STATE_CLASS
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from custom_components.catwandconnect import live

from .common import (
    ACTIVITY,
    PLAY_SESSION,
    PLAY_SESSION_EVENT,
    SESSIONS_TODAY,
    set_up,
    state_of,
    until,
)
from .fake_robot import FakeRobot


@pytest.fixture(autouse=True)
def fast_reconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reconnect within milliseconds instead of seconds."""
    monkeypatch.setattr(live, "RECONNECT_DELAYS", (0.01, 0.02, 0.05))


async def test_gives_the_robot_home_assistant_s_time_on_connect(
    hass: HomeAssistant, robot: FakeRobot
) -> None:
    await hass.config.async_update(time_zone="Europe/Paris")
    before = time.time() * 1000
    await set_up(hass, robot)
    await until(lambda: robot.clock is not None)

    assert before - 1000 <= robot.clock["epochMs"] <= time.time() * 1000 + 1000
    offset = dt_util.now().utcoffset()
    assert robot.clock["offset"] == int(offset.total_seconds() // 60)
    assert robot.clock["zone"] == "Europe/Paris"
    assert robot.time_headers == ["home_assistant"]


async def test_says_hello_so_the_journal_credits_home_assistant(
    hass: HomeAssistant, robot: FakeRobot
) -> None:
    await set_up(hass, robot)
    await until(lambda: robot.hello_clients == 1)
    assert {"t": "hello", "client": "home_assistant"} in robot.ws_frames


async def test_sets_the_time_again_after_the_robot_comes_back(
    hass: HomeAssistant, robot: FakeRobot
) -> None:
    await set_up(hass, robot)
    await until(lambda: len(robot.time_headers) == 1)
    robot.clock = None  # a restart forgets it
    await robot.disconnect()
    await until(lambda: robot.clock is not None)
    assert len(robot.time_headers) == 2


async def test_creates_the_event_entity_and_the_sensor(
    hass: HomeAssistant, robot: FakeRobot
) -> None:
    await set_up(hass, robot)
    event = hass.states.get(PLAY_SESSION_EVENT)
    assert event.state == STATE_UNKNOWN  # no event since it was created
    assert event.attributes[ATTR_EVENT_TYPES] == ["started", "ended", "stopped", "refused"]
    assert event.attributes["friendly_name"] == "CatWandConnect Play session"
    today = hass.states.get(SESSIONS_TODAY)
    assert today.attributes[ATTR_STATE_CLASS] == "total_increasing"
    assert today.attributes["friendly_name"] == "CatWandConnect Sessions today"


async def test_each_journal_event_fires_the_event_entity(
    hass: HomeAssistant, robot: FakeRobot
) -> None:
    await set_up(hass, robot)
    fired: list[tuple[str, str, str | None]] = []

    def follow(event) -> None:
        new = event.data["new_state"]
        if event.data["entity_id"] != PLAY_SESSION_EVENT:
            return
        if new is not None and new.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            fired.append(
                (new.attributes[ATTR_EVENT_TYPE], new.attributes["source"], new.attributes["reason"])
            )

    hass.bus.async_listen("state_changed", follow)
    await robot.record("started", "device_interface")
    await robot.record("refused", "home_assistant_mqtt", "busy")
    await robot.record("refused", "home_assistant_mqtt", "busy")  # twice in a row: fires twice
    await until(lambda: len(fired) == 3)
    assert fired == [
        ("started", "device_interface", None),
        ("refused", "home_assistant_mqtt", "busy"),
        ("refused", "home_assistant_mqtt", "busy"),
    ]


async def test_commands_from_home_assistant_are_journaled_as_the_native_integration(
    hass: HomeAssistant, robot: FakeRobot
) -> None:
    await set_up(hass, robot)
    await hass.services.async_call("switch", "turn_on", {"entity_id": PLAY_SESSION}, blocking=True)
    await hass.services.async_call("switch", "turn_off", {"entity_id": PLAY_SESSION}, blocking=True)
    await until(lambda: hass.states.get(PLAY_SESSION_EVENT).attributes.get(ATTR_EVENT_TYPE) == "stopped")
    attributes = hass.states.get(PLAY_SESSION_EVENT).attributes
    assert attributes["source"] == "home_assistant_native"
    assert attributes["reason"] == "stop"
    assert [e["source"] for e in robot.journal_events] == ["home_assistant_native"] * 2


async def test_unknown_event_types_are_ignored(hass: HomeAssistant, robot: FakeRobot) -> None:
    await set_up(hass, robot)
    await robot.record("paused_for_a_nap", "schedule")
    await robot.record("ended", "schedule")  # a source this version doesn't know is passed on
    await until(lambda: hass.states.get(PLAY_SESSION_EVENT).attributes.get(ATTR_EVENT_TYPE) == "ended")
    assert hass.states.get(PLAY_SESSION_EVENT).attributes["source"] == "schedule"


async def test_sessions_today_follows_the_robot(hass: HomeAssistant, robot: FakeRobot) -> None:
    robot.sessions_today = 2
    await set_up(hass, robot)
    await until(lambda: state_of(hass, SESSIONS_TODAY) == "2")
    await robot.record("started")
    await until(lambda: state_of(hass, SESSIONS_TODAY) == "3")


async def test_sessions_today_is_unknown_while_the_robot_has_no_clock(
    hass: HomeAssistant, robot: FakeRobot
) -> None:
    robot.sessions_today = 2
    await set_up(hass, robot)
    await until(lambda: robot.clock is not None)
    robot.clock = None
    await robot.push_state()
    await until(lambda: state_of(hass, SESSIONS_TODAY) == STATE_UNKNOWN)


async def test_entities_go_unavailable_with_the_robot(hass: HomeAssistant, robot: FakeRobot) -> None:
    await set_up(hass, robot)
    await robot.go_offline()
    await until(lambda: state_of(hass, PLAY_SESSION_EVENT) == STATE_UNAVAILABLE)
    assert state_of(hass, SESSIONS_TODAY) == STATE_UNAVAILABLE
    robot.go_online()
    await until(lambda: state_of(hass, SESSIONS_TODAY) not in (None, STATE_UNAVAILABLE))


@pytest.mark.parametrize("robot_config", [{"journal": False}])
async def test_firmware_without_the_journal_gets_neither_entity(
    hass: HomeAssistant, robot: FakeRobot
) -> None:
    entry = await set_up(hass, robot)
    ids = {e.entity_id for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)}
    assert PLAY_SESSION_EVENT not in ids
    assert SESSIONS_TODAY not in ids
    assert PLAY_SESSION in ids
    assert state_of(hass, ACTIVITY) == "idle"


@pytest.mark.parametrize("robot_config", [{"journal": False}])
async def test_entities_appear_once_the_firmware_has_the_journal(
    hass: HomeAssistant, robot: FakeRobot
) -> None:
    await set_up(hass, robot)
    robot.journal = True  # updated: the restarted robot answers /api/journal
    await robot.disconnect()
    await until(lambda: hass.states.get(PLAY_SESSION_EVENT) is not None, timeout=10)
    await until(lambda: state_of(hass, SESSIONS_TODAY) == "0")
