"""The integration loads and unloads in Home Assistant."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.catwandconnect.const import DOMAIN

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
