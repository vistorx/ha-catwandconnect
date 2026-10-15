"""Firmware update entity: versions from the Update feed, and Install."""

from __future__ import annotations

import logging
from datetime import timedelta

import pytest
from homeassistant.components.update import (
    ATTR_IN_PROGRESS,
    ATTR_INSTALLED_VERSION,
    ATTR_LATEST_VERSION,
    ATTR_RELEASE_SUMMARY,
    ATTR_RELEASE_URL,
    ATTR_UPDATE_PERCENTAGE,
    SERVICE_INSTALL,
    UpdateEntityFeature,
)
from homeassistant.components.update import DOMAIN as UPDATE_DOMAIN
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_ENTITY_ID,
    ATTR_SUPPORTED_FEATURES,
    EVENT_STATE_CHANGED,
    STATE_OFF,
    STATE_ON,
    EntityCategory,
)
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.catwandconnect import firmware, live, update
from custom_components.catwandconnect.const import DOMAIN

from .common import ACTIVITY, FIRMWARE, set_up, state_of, until
from .fake_feed import IMAGE, FakeFeed, channel
from .fake_robot import FakeRobot

PIN = "2468"


@pytest.fixture(autouse=True)
def fast_reconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reconnect within milliseconds instead of seconds."""
    monkeypatch.setattr(live, "RECONNECT_DELAYS", (0.01, 0.02, 0.05))
    monkeypatch.setattr(update, "RESTART_GRACE", 0.02)


@pytest.fixture
async def feed(monkeypatch: pytest.MonkeyPatch, socket_enabled):
    """A running fake Update feed the integration reads instead of GitHub Pages."""
    fake = FakeFeed()
    await fake.start()
    monkeypatch.setattr(firmware, "FEED_URL", fake.url)
    yield fake
    await fake.close()


async def _install(hass: HomeAssistant) -> None:
    await hass.services.async_call(
        UPDATE_DOMAIN, SERVICE_INSTALL, {ATTR_ENTITY_ID: FIRMWARE}, blocking=True
    )


def _attr(hass: HomeAssistant, name: str):
    return hass.states.get(FIRMWARE).attributes.get(name)


async def _set_up(hass: HomeAssistant, robot: FakeRobot, pin: str = ""):
    """Add the robot and wait until the Update feed has been read."""
    entry = await set_up(hass, robot, pin)
    coordinator = hass.data[firmware.DATA_FEED]
    await until(lambda: coordinator.data is not None)
    await hass.async_block_till_done()
    return entry


async def test_old_feed_offers_no_update(
    hass: HomeAssistant, robot: FakeRobot, feed: FakeFeed, entity_registry: er.EntityRegistry
) -> None:
    await _set_up(hass, robot)
    state = hass.states.get(FIRMWARE)
    assert state.state == STATE_OFF
    assert state.attributes[ATTR_INSTALLED_VERSION] == "0.2.0"
    assert state.attributes[ATTR_LATEST_VERSION] == "0.2.0"
    assert state.attributes[ATTR_DEVICE_CLASS] == "firmware"
    assert state.attributes[ATTR_SUPPORTED_FEATURES] == (
        UpdateEntityFeature.INSTALL
        | UpdateEntityFeature.PROGRESS
        | UpdateEntityFeature.RELEASE_NOTES
    )
    entity = entity_registry.async_get(FIRMWARE)
    assert entity.entity_category is EntityCategory.CONFIG
    assert entity.unique_id == f"{robot.device_id}_firmware"
    assert "channels.json" in feed.requests


@pytest.mark.parametrize("robot_config", [{"version": "0.1.0"}])
async def test_newer_stable_is_offered_with_its_notes(
    hass: HomeAssistant, robot: FakeRobot, feed: FakeFeed
) -> None:
    feed.publish(stable=channel("0.2.0", "Firmware updates from Home Assistant."),
                 beta=channel("0.3.0-beta.1"))
    await _set_up(hass, robot)
    assert state_of(hass, FIRMWARE) == STATE_ON
    assert _attr(hass, ATTR_INSTALLED_VERSION) == "0.1.0"
    assert _attr(hass, ATTR_LATEST_VERSION) == "0.2.0"
    assert _attr(hass, ATTR_RELEASE_SUMMARY) == "Firmware updates from Home Assistant."
    assert _attr(hass, ATTR_RELEASE_URL) == (
        "https://github.com/vistorx/CatWandConnect/releases/tag/v0.2.0"
    )


@pytest.mark.parametrize("robot_config", [{"version": "0.2.0-beta.3"}])
async def test_beta_robot_without_channel_follows_beta(
    hass: HomeAssistant, robot: FakeRobot, feed: FakeFeed
) -> None:
    feed.publish(stable=channel("0.1.0"), beta=channel("0.2.0-beta.4"))
    await _set_up(hass, robot)
    assert _attr(hass, ATTR_LATEST_VERSION) == "0.2.0-beta.4"
    assert state_of(hass, FIRMWARE) == STATE_ON


@pytest.mark.parametrize(
    "robot_config", [{"version": "0.2.0-beta.3", "extra_info": {"channel": "stable"}}]
)
async def test_beta_robot_on_stable_is_not_offered_an_older_stable(
    hass: HomeAssistant, robot: FakeRobot, feed: FakeFeed
) -> None:
    feed.publish(stable=channel("0.1.0"), beta=channel("0.2.0-beta.4"))
    await _set_up(hass, robot)
    assert _attr(hass, ATTR_LATEST_VERSION) == "0.2.0-beta.3"
    assert state_of(hass, FIRMWARE) == STATE_OFF


@pytest.mark.parametrize("robot_config", [{"version": "0.1.0"}])
async def test_unreachable_feed_offers_nothing_quietly(
    hass: HomeAssistant,
    robot: FakeRobot,
    feed: FakeFeed,
    caplog: pytest.LogCaptureFixture,
    issue_registry: ir.IssueRegistry,
) -> None:
    feed.publish(stable=channel("0.2.0"))
    feed.status = 500
    caplog.set_level(logging.DEBUG, logger="custom_components.catwandconnect")
    await _set_up(hass, robot)
    assert state_of(hass, FIRMWARE) == STATE_OFF
    assert _attr(hass, ATTR_LATEST_VERSION) == "0.1.0"
    assert not [
        r for r in caplog.records
        if r.name.startswith("custom_components.catwandconnect") and r.levelno >= logging.WARNING
    ]
    assert "Update feed" in caplog.text
    assert not [i for i in issue_registry.issues.values() if i.domain == DOMAIN]


@pytest.mark.parametrize("robot_config", [{"version": "0.1.0"}])
async def test_feed_is_read_again_every_six_hours(
    hass: HomeAssistant, robot: FakeRobot, feed: FakeFeed
) -> None:
    await _set_up(hass, robot)
    assert state_of(hass, FIRMWARE) == STATE_OFF
    feed.publish(stable=channel("0.2.0"))
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(hours=6, seconds=1))
    await until(lambda: state_of(hass, FIRMWARE) == STATE_ON)
    assert feed.requests.count("channels.json") == 2


async def test_one_feed_read_for_all_robots(
    hass: HomeAssistant, robot: FakeRobot, feed: FakeFeed
) -> None:
    other = FakeRobot(name="CatWandConnect salon", device_id="aaaabbbbccccdddd")
    await other.start()
    try:
        await _set_up(hass, robot)
        await _set_up(hass, other)
        await until(lambda: state_of(hass, "update.catwandconnect_salon_firmware") == STATE_OFF)
        assert state_of(hass, "update.catwandconnect_salon_firmware") == STATE_OFF
        assert feed.requests.count("channels.json") == 1
    finally:
        for entry in hass.config_entries.async_entries(DOMAIN):
            await hass.config_entries.async_unload(entry.entry_id)
        await other.close()


@pytest.mark.parametrize(
    "robot_config", [{"version": "0.1.0", "chip": "ESP32-S3", "restart_version": "0.2.0"}]
)
async def test_install_uploads_the_image_and_shows_the_new_version(
    hass: HomeAssistant,
    robot: FakeRobot,
    feed: FakeFeed,
    device_registry: dr.DeviceRegistry,
) -> None:
    feed.publish(stable=channel("0.2.0"))
    feed.files["stable/catwandconnect-esp32s3-ota.bin"] = IMAGE + b"S3"
    await _set_up(hass, robot)
    seen: list[tuple[bool, float | None]] = []

    @callback
    def record(event: Event) -> None:
        if event.data["entity_id"] == FIRMWARE and event.data["new_state"]:
            attrs = event.data["new_state"].attributes
            seen.append((attrs.get(ATTR_IN_PROGRESS), attrs.get(ATTR_UPDATE_PERCENTAGE)))

    hass.bus.async_listen(EVENT_STATE_CHANGED, record)
    await _install(hass)

    assert robot.firmware_uploads == [IMAGE + b"S3"]
    assert "stable/catwandconnect-esp32s3-ota.bin" in feed.requests
    assert robot.restarts == 1
    assert state_of(hass, FIRMWARE) == STATE_OFF
    assert _attr(hass, ATTR_INSTALLED_VERSION) == "0.2.0"
    assert _attr(hass, ATTR_IN_PROGRESS) is False
    percentages = [p for busy, p in seen if busy and p is not None]
    assert len(set(percentages)) >= 3
    assert percentages == sorted(percentages)
    device = device_registry.async_get_device_by_identifier(
        (DOMAIN, robot.device_id), hass.config_entries.async_entries(DOMAIN)[0].entry_id
    )
    assert device.sw_version == "0.2.0"


@pytest.mark.parametrize(
    "robot_config",
    [{"version": "0.1.0", "restart_version": "0.2.0", "restart_closes_sockets": False}],
)
async def test_install_reconnects_when_the_restart_goes_unnoticed(
    hass: HomeAssistant, robot: FakeRobot, feed: FakeFeed
) -> None:
    feed.publish(stable=channel("0.2.0"))
    await _set_up(hass, robot)
    connections = robot.ws_connections
    await _install(hass)
    assert robot.ws_connections > connections
    assert _attr(hass, ATTR_INSTALLED_VERSION) == "0.2.0"
    assert state_of(hass, FIRMWARE) == STATE_OFF


@pytest.mark.parametrize(
    "robot_config", [{"version": "0.1.0", "pin": PIN, "restart_version": "0.2.0"}]
)
async def test_install_unlocks_with_the_stored_pin(
    hass: HomeAssistant, robot: FakeRobot, feed: FakeFeed
) -> None:
    feed.publish(stable=channel("0.2.0"))
    await _set_up(hass, robot, pin=PIN)
    await _install(hass)
    assert robot.firmware_uploads == [IMAGE]
    uploads = [c for c in robot.commands if c[1] == "/api/update"]
    # Unlocked before uploading, so the image is sent once.
    assert [authorized for *_, authorized in uploads] == [True]
    assert _attr(hass, ATTR_INSTALLED_VERSION) == "0.2.0"


@pytest.mark.parametrize("robot_config", [{"version": "0.1.0", "pin": PIN}])
async def test_install_with_a_changed_pin_asks_for_the_new_one(
    hass: HomeAssistant, robot: FakeRobot, feed: FakeFeed
) -> None:
    feed.publish(stable=channel("0.2.0"))
    entry = await _set_up(hass, robot, pin="1111")
    with pytest.raises(ConfigEntryAuthFailed):
        await _install(hass)
    assert robot.firmware_uploads == []
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [f["context"]["source"] for f in flows] == ["reauth"]
    assert flows[0]["context"]["entry_id"] == entry.entry_id
    assert _attr(hass, ATTR_IN_PROGRESS) is False


@pytest.mark.parametrize("activity", ["playing", "calibrating", "tuning_speed"])
@pytest.mark.parametrize("robot_config", [{"version": "0.1.0"}])
async def test_install_is_refused_while_the_robot_is_busy(
    hass: HomeAssistant, robot: FakeRobot, feed: FakeFeed, activity: str
) -> None:
    feed.publish(stable=channel("0.2.0"))
    await _set_up(hass, robot)
    await robot.set_activity(activity)
    await until(lambda: state_of(hass, ACTIVITY) == activity)
    with pytest.raises(HomeAssistantError) as err:
        await _install(hass)
    assert err.value.translation_key == "update_busy"
    assert not [p for p in feed.requests if p.endswith(".bin")]
    assert robot.firmware_uploads == []


@pytest.mark.parametrize("robot_config", [{"version": "0.1.0", "update_error": "wrong_chip"}])
async def test_refused_image_is_reported(
    hass: HomeAssistant, robot: FakeRobot, feed: FakeFeed
) -> None:
    feed.publish(stable=channel("0.2.0"))
    await _set_up(hass, robot)
    with pytest.raises(HomeAssistantError) as err:
        await _install(hass)
    assert err.value.translation_key == "command_refused"
    assert err.value.translation_placeholders == {"error": "wrong_chip"}
    assert _attr(hass, ATTR_IN_PROGRESS) is False
    assert state_of(hass, FIRMWARE) == STATE_ON


@pytest.mark.parametrize("robot_config", [{"version": "0.1.0"}])
async def test_missing_image_is_reported(
    hass: HomeAssistant, robot: FakeRobot, feed: FakeFeed
) -> None:
    feed.publish(stable=channel("0.2.0"))
    feed.files.clear()
    await _set_up(hass, robot)
    with pytest.raises(HomeAssistantError) as err:
        await _install(hass)
    assert err.value.translation_key == "update_download_failed"
    assert robot.firmware_uploads == []
    assert _attr(hass, ATTR_IN_PROGRESS) is False


@pytest.mark.parametrize("robot_config", [{"version": "0.1.0"}])
async def test_robot_back_on_the_old_version_is_reported(
    hass: HomeAssistant, robot: FakeRobot, feed: FakeFeed, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(update, "RESTART_TIMEOUT", 0.5)
    feed.publish(stable=channel("0.2.0"))
    await _set_up(hass, robot)
    with pytest.raises(HomeAssistantError) as err:
        await _install(hass)
    assert err.value.translation_key == "update_not_applied"
    assert robot.firmware_uploads == [IMAGE]
    assert _attr(hass, ATTR_INSTALLED_VERSION) == "0.1.0"
    assert _attr(hass, ATTR_IN_PROGRESS) is False


@pytest.mark.parametrize(
    "robot_config", [{"version": "0.1.0", "restart_version": "0.2.0", "restart_delay": 1}]
)
async def test_robot_not_back_in_time_is_reported(
    hass: HomeAssistant, robot: FakeRobot, feed: FakeFeed, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(update, "RESTART_TIMEOUT", 0.3)
    feed.publish(stable=channel("0.2.0"))
    await _set_up(hass, robot)
    with pytest.raises(HomeAssistantError) as err:
        await _install(hass)
    assert err.value.translation_key == "update_no_restart"
    # Unavailable until the robot is back; no install shown as running.
    assert _attr(hass, ATTR_IN_PROGRESS) is not True
    await until(lambda: robot.restarts == 1, timeout=10)
    await until(lambda: _attr(hass, ATTR_INSTALLED_VERSION) == "0.2.0")
