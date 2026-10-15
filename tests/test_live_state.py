"""Live state over the robot's /ws: entities, availability, reconnect, rename."""

from __future__ import annotations

import asyncio

import pytest
from homeassistant.components.number import (
    ATTR_MAX,
    ATTR_MIN,
    ATTR_MODE,
    ATTR_STEP,
)
from homeassistant.components.sensor import ATTR_OPTIONS
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.catwandconnect import live
from custom_components.catwandconnect.const import DOMAIN

from .common import (
    ACTIVITY,
    H_MAX_SPEED,
    H_POSITION,
    V_MAX_SPEED,
    V_POSITION,
    set_up,
    state_of,
    until,
)
from .fake_robot import ACTIVITIES, FakeRobot

ALL = (ACTIVITY, H_POSITION, V_POSITION, H_MAX_SPEED, V_MAX_SPEED)


@pytest.fixture(autouse=True)
def fast_reconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reconnect within milliseconds instead of seconds."""
    monkeypatch.setattr(live, "RECONNECT_DELAYS", (0.01, 0.02, 0.05))


async def test_entities_show_the_robot_state(
    hass: HomeAssistant, robot: FakeRobot, entity_registry: er.EntityRegistry
) -> None:
    robot.h, robot.v = 75.0, 110.0
    robot.axes["horizontal"].update(min=40, max=150, maxSpeed=120)
    robot.axes["vertical"].update(min=50, max=130, maxSpeed=200)
    await set_up(hass, robot)

    activity = hass.states.get(ACTIVITY)
    assert activity.state == "idle"
    assert activity.attributes[ATTR_DEVICE_CLASS] == "enum"
    assert activity.attributes[ATTR_OPTIONS] == list(ACTIVITIES)

    h = hass.states.get(H_POSITION)
    assert float(h.state) == 75.0
    assert h.attributes[ATTR_MIN] == 40
    assert h.attributes[ATTR_MAX] == 150
    assert h.attributes[ATTR_STEP] == 1
    assert h.attributes[ATTR_MODE] == "slider"
    assert h.attributes[ATTR_UNIT_OF_MEASUREMENT] == "°"
    v = hass.states.get(V_POSITION)
    assert float(v.state) == 110.0
    assert (v.attributes[ATTR_MIN], v.attributes[ATTR_MAX]) == (50, 130)

    hs = hass.states.get(H_MAX_SPEED)
    assert float(hs.state) == 120
    assert hs.attributes[ATTR_MIN] == 10
    assert hs.attributes[ATTR_MAX] == 360
    assert hs.attributes[ATTR_STEP] == 5
    assert hs.attributes[ATTR_MODE] == "box"
    assert hs.attributes[ATTR_UNIT_OF_MEASUREMENT] == "°/s"
    assert float(state_of(hass, V_MAX_SPEED)) == 200

    unique_ids = {
        entity_registry.async_get(entity_id).unique_id for entity_id in ALL
    }
    assert unique_ids == {
        f"{robot.device_id}_{key}"
        for key in (
            "activity",
            "horizontal_position",
            "vertical_position",
            "horizontal_max_speed",
            "vertical_max_speed",
        )
    }


async def test_before_calibration_positions_are_bounded_to_the_safe_zone(
    hass: HomeAssistant, robot: FakeRobot
) -> None:
    robot.calibrated = False
    robot.axes["horizontal"].update(min=0, max=180)
    await set_up(hass, robot)

    h = hass.states.get(H_POSITION)
    assert (h.attributes[ATTR_MIN], h.attributes[ATTR_MAX]) == (60, 120)


async def test_pushed_state_updates_the_entities(
    hass: HomeAssistant, robot: FakeRobot
) -> None:
    await set_up(hass, robot)

    await robot.move(h=64.5, v=101)
    await until(lambda: state_of(hass, H_POSITION) == "64.5")
    assert float(state_of(hass, V_POSITION)) == 101
    assert state_of(hass, ACTIVITY) == "manual"

    for activity in ACTIVITIES:
        await robot.set_activity(activity)
        await until(lambda a=activity: state_of(hass, ACTIVITY) == a)


async def test_unknown_activity_reads_as_unknown(
    hass: HomeAssistant, robot: FakeRobot
) -> None:
    await set_up(hass, robot)
    robot.activity = "dancing"  # a future firmware's activity
    await robot.push_state()
    await until(lambda: state_of(hass, ACTIVITY) == "unknown")


async def test_other_messages_are_ignored(
    hass: HomeAssistant, robot: FakeRobot
) -> None:
    await set_up(hass, robot)
    for frame in (
        '{"t":"calibration","step":"stow"}',
        "not json",
        "[1, 2]",
        b"\x00\x01",
    ):
        await robot.send_raw(frame)
    await robot.move(h=70)
    await until(lambda: state_of(hass, H_POSITION) == "70")
    assert robot.ws_connections == 1
    assert state_of(hass, ACTIVITY) == "manual"


async def test_disconnect_makes_entities_unavailable_until_reconnect(
    hass: HomeAssistant, robot: FakeRobot
) -> None:
    await set_up(hass, robot)
    await robot.go_offline()
    await until(
        lambda: all(state_of(hass, entity_id) == STATE_UNAVAILABLE for entity_id in ALL)
    )
    # Several attempts fail while the robot is away.
    await until(lambda: robot.requests.count(("GET", "/ws")) >= 3)
    assert all(state_of(hass, entity_id) == STATE_UNAVAILABLE for entity_id in ALL)

    # Settings changed while away (on the Device interface) are read back.
    robot.axes["horizontal"].update(min=30, max=160, maxSpeed=250)
    robot.h = 33
    robot.go_online()
    await until(lambda: state_of(hass, H_MAX_SPEED) not in (None, STATE_UNAVAILABLE))
    assert float(state_of(hass, H_MAX_SPEED)) == 250
    assert float(state_of(hass, H_POSITION)) == 33
    h = hass.states.get(H_POSITION)
    assert (h.attributes[ATTR_MIN], h.attributes[ATTR_MAX]) == (30, 160)
    assert all(state_of(hass, entity_id) != STATE_UNAVAILABLE for entity_id in ALL)
    assert robot.ws_connections == 2


async def test_dropped_socket_reconnects_and_rereads_settings(
    hass: HomeAssistant, robot: FakeRobot
) -> None:
    await set_up(hass, robot)
    settings_reads = robot.requests.count(("GET", "/api/settings"))
    robot.axes["vertical"]["maxSpeed"] = 45
    await robot.disconnect()
    await until(lambda: robot.ws_connections == 2)
    await until(lambda: state_of(hass, V_MAX_SPEED) == "45")
    assert robot.requests.count(("GET", "/api/settings")) == settings_reads + 1


@pytest.mark.parametrize("activity", ["calibrating", "tuning_speed"])
async def test_settings_are_reread_when_calibration_or_speed_tuning_ends(
    hass: HomeAssistant, robot: FakeRobot, activity: str
) -> None:
    await set_up(hass, robot)
    await robot.set_activity(activity)
    await until(lambda: state_of(hass, ACTIVITY) == activity)

    robot.axes["horizontal"].update(min=20, max=170, maxSpeed=300)
    await robot.set_activity("stowing")
    await until(lambda: state_of(hass, H_MAX_SPEED) == "300")
    h = hass.states.get(H_POSITION)
    assert (h.attributes[ATTR_MIN], h.attributes[ATTR_MAX]) == (20, 170)


async def test_rename_follows_on_the_device_and_entry(
    hass: HomeAssistant, robot: FakeRobot, device_registry: dr.DeviceRegistry
) -> None:
    entry = await set_up(hass, robot)
    await robot.rename("Minou")
    await until(lambda: entry.title == "Minou")
    device = device_registry.async_get_device_by_identifier(
        (DOMAIN, robot.device_id), entry.entry_id
    )
    assert device.name == "Minou"


async def test_rename_keeps_the_name_given_in_home_assistant(
    hass: HomeAssistant, robot: FakeRobot, device_registry: dr.DeviceRegistry
) -> None:
    entry = await set_up(hass, robot)
    device = device_registry.async_get_device_by_identifier(
        (DOMAIN, robot.device_id), entry.entry_id
    )
    device_registry.async_update_device(device.id, name_by_user="Living room toy")

    await robot.rename("Minou")
    await until(lambda: entry.title == "Minou")
    device = device_registry.async_get(device.id)
    assert device.name == "Minou"
    assert device.name_by_user == "Living room toy"


async def test_unload_closes_the_socket(hass: HomeAssistant, robot: FakeRobot) -> None:
    entry = await set_up(hass, robot)
    assert robot.ws_clients == 1

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    await until(lambda: robot.ws_clients == 0)
    await asyncio.sleep(0.1)
    assert robot.ws_connections == 1


async def test_unload_while_the_robot_is_away(
    hass: HomeAssistant, robot: FakeRobot
) -> None:
    entry = await set_up(hass, robot)
    await robot.go_offline()
    await until(lambda: state_of(hass, ACTIVITY) == STATE_UNAVAILABLE)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    requests = len(robot.requests)
    await asyncio.sleep(0.2)
    assert len(robot.requests) == requests
