"""Shared fixtures."""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest

from .fake_robot import FakeRobot


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let Home Assistant load custom_components/ in every test."""
    return


@pytest.fixture
def robot_config() -> dict:
    """Overrides for the fake robot; parametrize or override per test."""
    return {}


@pytest.fixture
async def robot(robot_config: dict, socket_enabled) -> AsyncGenerator[FakeRobot]:
    """A running fake robot on 127.0.0.1.

    Home Assistant's test harness blocks sockets; the fake robot is a real
    local server, so it re-enables them (pytest-socket still limits hosts to
    127.0.0.1).
    """
    fake = FakeRobot(**robot_config)
    await fake.start()
    yield fake
    await fake.close()
