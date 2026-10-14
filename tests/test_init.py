"""The integration loads and unloads in Home Assistant."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
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
