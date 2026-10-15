"""Shared fixtures."""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from custom_components.catwandconnect.const import DOMAIN

from .fake_robot import FakeRobot


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let Home Assistant load custom_components/ in every test."""
    return


@pytest.fixture(autouse=True)
def no_update_feed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never read the real Update feed: point it at a closed local port.

    Tests about firmware updates start a fake feed (tests/fake_feed.py) instead.
    """
    from custom_components.catwandconnect import firmware

    monkeypatch.setattr(firmware, "FEED_URL", "http://127.0.0.1:9/flasher/")


@pytest.fixture
def robot_config() -> dict:
    """Overrides for the fake robot; parametrize or override per test."""
    return {}


@pytest.fixture
async def robot(
    hass: HomeAssistant, robot_config: dict, socket_enabled
) -> AsyncGenerator[FakeRobot]:
    """A running fake robot on 127.0.0.1.

    Home Assistant's test harness blocks sockets; the fake robot is a real
    local server, so it re-enables them (pytest-socket still limits hosts to
    127.0.0.1).

    Entries still loaded at the end of a test are unloaded before the robot
    stops, so their /ws connection doesn't race the server's shutdown.
    """
    fake = FakeRobot(**robot_config)
    await fake.start()
    yield fake
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED:
            await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    await fake.close()
