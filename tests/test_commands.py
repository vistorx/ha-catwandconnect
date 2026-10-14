"""Commands from Home Assistant: what the robot receives, and what HA shows."""

from __future__ import annotations

import logging

import pytest
from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN
from homeassistant.components.button import SERVICE_PRESS
from homeassistant.components.number import (
    ATTR_MAX,
    ATTR_MIN,
    ATTR_MODE,
    ATTR_STEP,
    ATTR_VALUE,
    SERVICE_SET_VALUE,
)
from homeassistant.components.number import (
    DOMAIN as NUMBER_DOMAIN,
)
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_UNIT_OF_MEASUREMENT,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import entity_registry as er

from .common import (
    ACTIVITY,
    H_POSITION,
    PLAY_SESSION,
    SESSION_DURATION,
    STOW,
    V_MAX_SPEED,
    set_up,
    state_of,
    until,
)
from .fake_robot import FakeRobot

PIN = "2468"


async def _turn(hass: HomeAssistant, service: str) -> None:
    await hass.services.async_call(
        SWITCH_DOMAIN, service, {ATTR_ENTITY_ID: PLAY_SESSION}, blocking=True
    )


async def _set(hass: HomeAssistant, entity_id: str, value: float) -> None:
    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: entity_id, ATTR_VALUE: value},
        blocking=True,
    )


async def test_new_entities_have_stable_ids(
    hass: HomeAssistant, robot: FakeRobot, entity_registry: er.EntityRegistry
) -> None:
    await set_up(hass, robot)
    assert {
        entity_registry.async_get(entity_id).unique_id
        for entity_id in (PLAY_SESSION, SESSION_DURATION, STOW)
    } == {
        f"{robot.device_id}_{key}"
        for key in ("play_session", "session_duration", "stow")
    }


async def test_play_session_switch_starts_and_stops_a_session(
    hass: HomeAssistant, robot: FakeRobot
) -> None:
    await set_up(hass, robot)
    assert state_of(hass, PLAY_SESSION) == STATE_OFF

    await _turn(hass, SERVICE_TURN_ON)
    await until(lambda: state_of(hass, PLAY_SESSION) == STATE_ON)
    assert ("POST", "/api/play", {"action": "start"}, False) in robot.commands
    assert robot.play_remaining == 600  # the stored Session duration

    await _turn(hass, SERVICE_TURN_OFF)
    await until(lambda: state_of(hass, PLAY_SESSION) == STATE_OFF)
    assert robot.commands[-1] == ("POST", "/api/play", {"action": "stop"}, False)
    assert state_of(hass, ACTIVITY) == "stowing"


async def test_play_session_switch_follows_the_activity(
    hass: HomeAssistant, robot: FakeRobot
) -> None:
    await set_up(hass, robot)
    await robot.set_activity("playing")
    await until(lambda: state_of(hass, PLAY_SESSION) == STATE_ON)
    await robot.move(h=70)  # the joystick ends the session
    await until(lambda: state_of(hass, PLAY_SESSION) == STATE_OFF)


@pytest.mark.parametrize(
    ("robot_config", "translation_key"),
    [
        ({"calibrated": False}, "play_not_calibrated"),
        ({"activity": "stowing"}, "play_busy"),
    ],
)
async def test_refused_play_session_start(
    hass: HomeAssistant,
    robot: FakeRobot,
    caplog: pytest.LogCaptureFixture,
    translation_key: str,
) -> None:
    await set_up(hass, robot)
    with (
        caplog.at_level(logging.WARNING),
        pytest.raises(HomeAssistantError) as err,
    ):
        await _turn(hass, SERVICE_TURN_ON)
    assert err.value.translation_key == translation_key
    assert state_of(hass, PLAY_SESSION) == STATE_OFF
    assert "Play session" in caplog.text
    assert any(r.levelno == logging.WARNING for r in caplog.records)


async def test_session_duration_number(hass: HomeAssistant, robot: FakeRobot) -> None:
    robot.session_minutes = 12
    await set_up(hass, robot)
    duration = hass.states.get(SESSION_DURATION)
    assert float(duration.state) == 12
    assert (duration.attributes[ATTR_MIN], duration.attributes[ATTR_MAX]) == (1, 60)
    assert duration.attributes[ATTR_STEP] == 1
    assert duration.attributes[ATTR_MODE] == "box"
    assert duration.attributes[ATTR_UNIT_OF_MEASUREMENT] == "min"

    await _set(hass, SESSION_DURATION, 25)
    assert robot.commands[-1] == ("PUT", "/api/settings", {"sessionMinutes": 25}, False)
    await until(lambda: state_of(hass, SESSION_DURATION) == "25")

    await _turn(hass, SERVICE_TURN_ON)
    assert robot.play_remaining == 25 * 60


async def test_stow_button(hass: HomeAssistant, robot: FakeRobot) -> None:
    await set_up(hass, robot)
    await robot.set_activity("playing")
    await hass.services.async_call(
        BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: STOW}, blocking=True
    )
    assert robot.commands[-1] == ("POST", "/api/stow", None, False)
    await until(lambda: state_of(hass, ACTIVITY) == "stowing")


async def test_position_numbers_move_the_wand(
    hass: HomeAssistant, robot: FakeRobot
) -> None:
    await set_up(hass, robot)
    await _set(hass, H_POSITION, 100)
    assert robot.commands[-1] == (
        "POST",
        "/api/position",
        {"axis": "horizontal", "degrees": 100},
        False,
    )
    await until(lambda: state_of(hass, H_POSITION) == "100.0")
    assert state_of(hass, ACTIVITY) == "manual"


async def test_maximum_speed_numbers_change_the_settings(
    hass: HomeAssistant, robot: FakeRobot
) -> None:
    await set_up(hass, robot)
    await _set(hass, V_MAX_SPEED, 200)
    assert robot.commands[-1] == (
        "PUT",
        "/api/settings",
        {"axes": {"vertical": {"maxSpeed": 200}}},
        False,
    )
    assert robot.axes["vertical"]["maxSpeed"] == 200
    await until(lambda: state_of(hass, V_MAX_SPEED) == "200.0")


async def test_a_maximum_speed_below_the_minimum_takes_it_down(
    hass: HomeAssistant, robot: FakeRobot
) -> None:
    """Like over MQTT: HA knows only the maximum, so it isn't refused."""
    robot.axes["vertical"].update(maxSpeed=200, minSpeed=60)
    await set_up(hass, robot)
    await _set(hass, V_MAX_SPEED, 50)
    assert robot.commands[-1][2] == {"axes": {"vertical": {"maxSpeed": 50, "minSpeed": 5}}}
    assert robot.axes["vertical"]["maxSpeed"] == 50
    await until(lambda: state_of(hass, V_MAX_SPEED) == "50.0")


async def test_a_command_the_robot_cannot_take_raises(
    hass: HomeAssistant, robot: FakeRobot
) -> None:
    await set_up(hass, robot)
    robot.offline = True  # answers 503 to everything, socket still up
    with pytest.raises(HomeAssistantError) as err:
        await _set(hass, H_POSITION, 100)
    assert err.value.translation_key == "command_failed"
    with pytest.raises(HomeAssistantError) as err:
        await _turn(hass, SERVICE_TURN_ON)
    assert err.value.translation_key == "command_failed"


# --------------------------------------------------------------------- PIN


@pytest.mark.parametrize("robot_config", [{"pin": PIN}])
async def test_pin_protected_command_unlocks_with_the_stored_pin_and_retries(
    hass: HomeAssistant, robot: FakeRobot
) -> None:
    await set_up(hass, robot, pin=PIN)
    body = {"axes": {"vertical": {"maxSpeed": 200}}}
    await _set(hass, V_MAX_SPEED, 200)
    assert robot.commands == [
        ("PUT", "/api/settings", body, False),
        ("POST", "/api/auth/unlock", {"pin": PIN}, False),
        ("PUT", "/api/settings", body, True),
    ]
    assert robot.axes["vertical"]["maxSpeed"] == 200

    # The token is kept: the next protected call sends it straight away.
    await _set(hass, V_MAX_SPEED, 150)
    assert robot.commands[3:] == [
        ("PUT", "/api/settings", {"axes": {"vertical": {"maxSpeed": 150}}}, True)
    ]

    # Once the robot forgets it (restart, PIN changed), it unlocks again.
    robot.tokens.clear()
    await _set(hass, V_MAX_SPEED, 100)
    assert [command[:2] for command in robot.commands[4:]] == [
        ("PUT", "/api/settings"),
        ("POST", "/api/auth/unlock"),
        ("PUT", "/api/settings"),
    ]
    assert robot.axes["vertical"]["maxSpeed"] == 100


@pytest.mark.parametrize("robot_config", [{"pin": PIN}])
async def test_play_commands_never_unlock(hass: HomeAssistant, robot: FakeRobot) -> None:
    await set_up(hass, robot, pin=PIN)
    await _turn(hass, SERVICE_TURN_ON)
    await _set(hass, SESSION_DURATION, 20)
    await _set(hass, H_POSITION, 80)
    await hass.services.async_call(
        BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: STOW}, blocking=True
    )
    assert ("POST", "/api/auth/unlock") not in [c[:2] for c in robot.commands]


@pytest.mark.parametrize(
    ("robot_config", "stored_pin"), [({"pin": PIN}, "1111"), ({"pin": PIN}, "")]
)
async def test_wrong_or_missing_stored_pin_raises_auth_failed(
    hass: HomeAssistant, robot: FakeRobot, stored_pin: str
) -> None:
    await set_up(hass, robot, pin=stored_pin)
    with pytest.raises(ConfigEntryAuthFailed):
        await _set(hass, V_MAX_SPEED, 200)
    assert [c[:2] for c in robot.commands].count(("PUT", "/api/settings")) == 1
    assert robot.axes["vertical"]["maxSpeed"] == 90


@pytest.mark.parametrize("robot_config", [{"pin": PIN, "locked_for": 120}])
async def test_locked_out_raises_with_the_wait(
    hass: HomeAssistant, robot: FakeRobot
) -> None:
    await set_up(hass, robot, pin=PIN)
    with pytest.raises(HomeAssistantError) as err:
        await _set(hass, V_MAX_SPEED, 200)
    assert err.value.translation_key == "locked_out"
    assert err.value.translation_placeholders == {"retry_after": "120"}
