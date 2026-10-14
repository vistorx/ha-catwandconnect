"""The integration loads and unloads in Home Assistant."""

from __future__ import annotations

import pytest

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.catwandconnect.const import CONF_PIN, DOMAIN

from .fake_robot import FakeRobot


async def test_component_sets_up(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, DOMAIN, {})


async def test_entry_loads_and_unloads(hass: HomeAssistant, robot: FakeRobot) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=robot.device_id,
        data={CONF_HOST: robot.host},
        title=robot.name,
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_entry_registers_the_robot_device(
    hass: HomeAssistant, robot: FakeRobot, device_registry: dr.DeviceRegistry
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=robot.device_id,
        data={CONF_HOST: robot.host, CONF_PIN: ""},
        title=robot.name,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    device = device_registry.async_get_device_by_identifier(
        (DOMAIN, robot.device_id), entry.entry_id
    )
    assert device is not None
    assert device.name == "CatWandConnect"
    assert device.manufacturer == "CatWandConnect"
    assert device.model == "CatWandConnect"
    assert device.hw_version == "ESP32-D0WD-V3"
    assert device.sw_version == "0.2.0"
    assert device.configuration_url == f"http://{robot.host}/"


async def test_entry_retries_while_robot_is_unreachable(
    hass: HomeAssistant, robot: FakeRobot
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=robot.device_id,
        data={CONF_HOST: robot.host, CONF_PIN: ""},
        title=robot.name,
    )
    entry.add_to_hass(hass)
    await robot.close()
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


TOO_OLD = [{"api": None, "version": "0.1.0"}, {"api": 0, "version": "0.2.0-beta.1"}]


def _add(hass: HomeAssistant, robot: FakeRobot) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=robot.device_id,
        data={CONF_HOST: robot.host, CONF_PIN: ""},
        title=robot.name,
    )
    entry.add_to_hass(hass)
    return entry


@pytest.mark.parametrize("robot_config", TOO_OLD, ids=["api_missing", "api_0"])
async def test_firmware_too_old_raises_a_repair_issue(
    hass: HomeAssistant,
    robot: FakeRobot,
    issue_registry: ir.IssueRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    entry = _add(hass, robot)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert er.async_entries_for_config_entry(entity_registry, entry.entry_id) == []
    issue = issue_registry.async_get_issue(DOMAIN, f"firmware_too_old_{entry.entry_id}")
    assert issue is not None
    assert issue.translation_key == "firmware_too_old"
    assert issue.severity is ir.IssueSeverity.ERROR
    assert not issue.is_fixable
    assert issue.translation_placeholders == {
        "name": "CatWandConnect",
        "version": robot.version,
        "min_firmware": "0.2.0-beta.2",
        "update_url": "https://vistorx.github.io/CatWandConnect/install/#updating-building-from-source",
    }


@pytest.mark.parametrize("robot_config", [TOO_OLD[0]])
async def test_repair_issue_goes_once_the_robot_is_updated(
    hass: HomeAssistant, robot: FakeRobot, issue_registry: ir.IssueRegistry
) -> None:
    entry = _add(hass, robot)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    issue_id = f"firmware_too_old_{entry.entry_id}"
    assert issue_registry.async_get_issue(DOMAIN, issue_id) is not None

    robot.api, robot.version = 1, "0.2.0"
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert issue_registry.async_get_issue(DOMAIN, issue_id) is None


@pytest.mark.parametrize("robot_config", [TOO_OLD[0]])
async def test_repair_issue_goes_with_the_entry(
    hass: HomeAssistant, robot: FakeRobot, issue_registry: ir.IssueRegistry
) -> None:
    entry = _add(hass, robot)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert issue_registry.async_get_issue(DOMAIN, f"firmware_too_old_{entry.entry_id}") is None
