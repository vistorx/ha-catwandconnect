"""The diagnostics download: what it shows and what it hides."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from .common import set_up
from .fake_robot import FakeRobot

REDACTED = "**REDACTED**"


@pytest.mark.parametrize(
    "robot_config", [{"pin": "2468", "hostname": "salon.local"}]
)
async def test_diagnostics_hide_network_and_secrets(
    hass: HomeAssistant, hass_client: ClientSessionGenerator, robot: FakeRobot
) -> None:
    entry = await set_up(hass, robot, pin="2468")
    diag = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    assert diag["entry"] == {"host": REDACTED, "pin": REDACTED}

    info = diag["info"]
    for key in ("ssid", "ip", "mac", "hostname", "name"):
        assert info[key] == REDACTED, key
    assert info["version"] == "0.2.0"
    assert info["api"] == 1
    assert info["id"] == "3f9a1c2b7d4e6f80"  # Device ID: random, not personal
    assert info["rssi"] == -61

    assert diag["settings"]["sessionMinutes"] == 10
    assert diag["settings"]["axes"]["horizontal"]["maxSpeed"] == 90

    assert diag["state"]["activity"] == "idle"
    assert diag["state"]["name"] == REDACTED

    text = repr(diag)
    for secret in ("2468", "Home", "192.168.1.20", "24:6F:28", "salon", "127.0.0.1"):
        assert secret not in text, secret


@pytest.mark.parametrize(
    "robot_config",
    [{"extra_info": {"mqtt": {
        "host": "broker.lan", "user": "robot", "password": "s3cret", "port": 1883
    }}}],
)
async def test_diagnostics_redact_broker_address_and_credentials(
    hass: HomeAssistant, hass_client: ClientSessionGenerator, robot: FakeRobot
) -> None:
    entry = await set_up(hass, robot)
    diag = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    broker = diag["info"]["mqtt"]
    assert broker == {
        "host": REDACTED, "user": REDACTED, "password": REDACTED, "port": 1883
    }


async def test_diagnostics_of_an_unreachable_robot(
    hass: HomeAssistant, hass_client: ClientSessionGenerator, robot: FakeRobot
) -> None:
    entry = await set_up(hass, robot)
    await robot.go_offline()
    diag = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    assert diag["info"] == {"error": "unreachable"}
    assert diag["settings"] == {"error": "unreachable"}
