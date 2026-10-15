"""Adding a robot through the config flow, against the fake robot."""

from __future__ import annotations

from ipaddress import ip_address

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from homeassistant import config_entries
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.catwandconnect.const import CONF_PIN, DOMAIN

from .fake_robot import FakeRobot


async def test_user_adds_robot_without_pin(hass: HomeAssistant, robot: FakeRobot) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: robot.host}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "CatWandConnect"
    assert result["data"] == {CONF_HOST: robot.host, CONF_PIN: ""}
    assert result["result"].unique_id == robot.device_id


async def _submit_host(hass: HomeAssistant, robot: FakeRobot):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: robot.host}
    )


@pytest.mark.parametrize("robot_config", [{"pin": "2468"}])
async def test_user_adds_robot_with_pin(hass: HomeAssistant, robot: FakeRobot) -> None:
    result = await _submit_host(hass, robot)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "pin"
    assert result["description_placeholders"] == {"name": "CatWandConnect"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PIN: "2468"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_HOST: robot.host, CONF_PIN: "2468"}
    assert result["result"].unique_id == robot.device_id


@pytest.mark.parametrize("robot_config", [{"pin": "2468"}])
async def test_wrong_pin_asks_again(hass: HomeAssistant, robot: FakeRobot) -> None:
    result = await _submit_host(hass, robot)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PIN: "0000"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "pin"
    assert result["errors"] == {"base": "wrong_pin"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PIN: "2468"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_PIN] == "2468"


@pytest.mark.parametrize("robot_config", [{"pin": "2468"}])
async def test_locked_out_says_how_long_to_wait(
    hass: HomeAssistant, robot: FakeRobot
) -> None:
    result = await _submit_host(hass, robot)
    for _ in range(5):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PIN: "0000"}
        )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PIN: "2468"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "pin"
    assert result["errors"] == {"base": "locked_out"}
    assert result["description_placeholders"]["retry_after"] == "30"


@pytest.mark.parametrize(
    "robot_config",
    [{"api": None, "version": "0.1.0"}, {"api": 0, "version": "0.2.0-beta.1"}],
    ids=["api_missing", "api_0"],
)
async def test_firmware_too_old_is_refused(hass: HomeAssistant, robot: FakeRobot) -> None:
    result = await _submit_host(hass, robot)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "firmware_too_old"
    assert result["description_placeholders"] == {
        "min_firmware": "0.2.0-beta.2",
        "update_url": "https://vistorx.github.io/CatWandConnect/install/#updating-building-from-source",
    }


async def test_unreachable_host_shows_cannot_connect(
    hass: HomeAssistant, robot: FakeRobot
) -> None:
    host = robot.host
    await robot.close()
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: host}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "cannot_connect"}


def _zeroconf(robot: FakeRobot, **txt: str) -> ZeroconfServiceInfo:
    """What Home Assistant's zeroconf hands over for the robot's service."""
    ip, port = robot.host.split(":")
    properties = {
        "id": robot.device_id,
        "api": str(robot.api),
        "version": robot.version,
        "name": robot.name,
    } | txt
    return ZeroconfServiceInfo(
        ip_address=ip_address(ip),
        ip_addresses=[ip_address(ip)],
        hostname="catwandconnect.local.",
        name="CatWandConnect._catwandconnect._tcp.local.",
        port=int(port),
        type="_catwandconnect._tcp.local.",
        properties=properties,
    )


async def test_discovered_robot_is_added_after_confirm(
    hass: HomeAssistant, robot: FakeRobot
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=_zeroconf(robot)
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "zeroconf_confirm"
    assert result["description_placeholders"] == {"name": "CatWandConnect"}

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "CatWandConnect"
    assert result["data"] == {CONF_HOST: robot.host, CONF_PIN: ""}
    assert result["result"].unique_id == robot.device_id


@pytest.mark.parametrize("robot_config", [{"pin": "2468"}])
async def test_discovered_robot_with_pin_asks_it(
    hass: HomeAssistant, robot: FakeRobot
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=_zeroconf(robot)
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "pin"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PIN: "2468"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_HOST: robot.host, CONF_PIN: "2468"}


@pytest.mark.parametrize("txt", [{"api": "0"}, {"api": ""}, {"api": "x"}])
async def test_discovered_old_firmware_is_refused(
    hass: HomeAssistant, robot: FakeRobot, txt: dict[str, str]
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_ZEROCONF},
        data=_zeroconf(robot, **txt),
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "firmware_too_old"
    assert result["description_placeholders"]["min_firmware"] == "0.2.0-beta.2"


async def test_discovered_robot_unreachable_on_confirm(
    hass: HomeAssistant, robot: FakeRobot
) -> None:
    info = _zeroconf(robot)
    await robot.close()
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=info
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"


def _existing_entry(hass: HomeAssistant, robot: FakeRobot, host: str) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=robot.device_id,
        data={CONF_HOST: host, CONF_PIN: ""},
        title=robot.name,
    )
    entry.add_to_hass(hass)
    return entry


async def test_rediscovery_updates_host_without_duplicate(
    hass: HomeAssistant, robot: FakeRobot
) -> None:
    entry = _existing_entry(hass, robot, "192.168.1.20")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=_zeroconf(robot)
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == robot.host
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


async def test_user_adding_known_robot_updates_host(
    hass: HomeAssistant, robot: FakeRobot
) -> None:
    entry = _existing_entry(hass, robot, "192.168.1.20")
    result = await _submit_host(hass, robot)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == robot.host
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


async def test_host_that_is_not_a_robot_shows_cannot_connect(
    hass: HomeAssistant, socket_enabled
) -> None:
    """Another web server (a router, a printer) answers 404 pages, not JSON."""
    server = TestServer(web.Application(), host="127.0.0.1")
    await server.start_server()
    try:
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: f"127.0.0.1:{server.port}"}
        )
    finally:
        await server.close()
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


@pytest.mark.parametrize("robot_config", [{"pin": "2468"}])
async def test_robot_gone_during_pin_step(hass: HomeAssistant, robot: FakeRobot) -> None:
    result = await _submit_host(hass, robot)
    await robot.close()
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PIN: "2468"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "pin"
    assert result["errors"] == {"base": "cannot_connect"}


# ---------------------------------------------------------------- reauth


def _entry(robot: FakeRobot, pin: str) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=robot.device_id,
        data={CONF_HOST: robot.host, CONF_PIN: pin},
        title=robot.name,
    )
    return entry


@pytest.mark.parametrize("robot_config", [{"pin": "1357"}])
async def test_reauth_stores_the_new_pin(hass: HomeAssistant, robot: FakeRobot) -> None:
    entry = _entry(robot, "2468")
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["description_placeholders"] == {"name": "CatWandConnect"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PIN: "1357"}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data == {CONF_HOST: robot.host, CONF_PIN: "1357"}


@pytest.mark.parametrize("robot_config", [{"pin": "1357"}])
async def test_reauth_wrong_pin_asks_again(hass: HomeAssistant, robot: FakeRobot) -> None:
    entry = _entry(robot, "2468")
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PIN: "2468"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": "wrong_pin"}
    assert entry.data[CONF_PIN] == "2468"


@pytest.mark.parametrize("robot_config", [{"pin": "1357", "locked_for": 60}])
async def test_reauth_locked_out_says_how_long_to_wait(
    hass: HomeAssistant, robot: FakeRobot
) -> None:
    entry = _entry(robot, "2468")
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PIN: "1357"}
    )
    assert result["errors"] == {"base": "locked_out"}
    assert result["description_placeholders"]["retry_after"] == "60"


@pytest.mark.parametrize("robot_config", [{"pin": "1357"}])
async def test_reauth_unreachable_robot_shows_cannot_connect(
    hass: HomeAssistant, robot: FakeRobot
) -> None:
    entry = _entry(robot, "2468")
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    await robot.go_offline()
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PIN: "1357"}
    )
    assert result["errors"] == {"base": "cannot_connect"}
