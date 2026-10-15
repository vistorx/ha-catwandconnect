"""Firmware update entity: the robot's version, the Update feed's, and Install.

Installed version: what the robot reports in GET /api/info, read again each
time it reconnects. Latest version: the Update feed's version for the robot's
Update channel, when it is strictly newer and has an OTA image for the robot's
chip family; otherwise the installed one, so no update is offered.

Install downloads the OTA image from the flasher site, uploads it to the
robot's POST /api/update, then waits for the robot to come back on the new
version.
"""

from __future__ import annotations

import asyncio
from typing import Any

from homeassistant.components.update import (
    UpdateDeviceClass,
    UpdateEntity,
    UpdateEntityDescription,
    UpdateEntityFeature,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CatWandConnectConfigEntry
from .const import DOMAIN
from .entity import CatWandConnectEntity
from .firmware import (
    DownloadFailed,
    FeedChannel,
    FeedCoordinator,
    async_download,
    async_get_feed,
    chip_family,
    is_newer,
    robot_channel,
)
from .live import RobotLive

PARALLEL_UPDATES = 0

# Activities during which an update would cut something short.
BUSY_ACTIVITIES = ("playing", "calibrating", "tuning_speed")
# Seconds the robot gets to write the image, restart and reconnect.
RESTART_TIMEOUT = 180.0
# Seconds after the upload before dropping a socket the restart left looking alive.
RESTART_GRACE = 3.0

# Share of the progress bar each phase ends at.
DOWNLOAD_END = 30
UPLOAD_END = 95

FIRMWARE = UpdateEntityDescription(
    key="firmware",
    translation_key="firmware",
    device_class=UpdateDeviceClass.FIRMWARE,
    entity_category=EntityCategory.CONFIG,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CatWandConnectConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the Firmware update entity."""
    feed = async_get_feed(hass)
    async_add_entities([FirmwareUpdate(entry.runtime_data, FIRMWARE, feed)])


class FirmwareUpdate(CatWandConnectEntity, UpdateEntity):
    """The robot's firmware, and the Update feed's for its Update channel."""

    _platform_domain = "update"
    _attr_supported_features = (
        UpdateEntityFeature.INSTALL
        | UpdateEntityFeature.PROGRESS
        | UpdateEntityFeature.RELEASE_NOTES
    )

    def __init__(
        self, live: RobotLive, description: UpdateEntityDescription, feed: FeedCoordinator
    ) -> None:
        super().__init__(live, description)
        self.feed = feed
        self._attr_in_progress = False
        self._attr_update_percentage = None

    @property
    def available(self) -> bool:
        """Available while the robot is connected, and throughout an install."""
        return self.live.connected or bool(self._attr_in_progress)

    async def async_added_to_hass(self) -> None:
        """Follow the robot and the Update feed."""
        await super().async_added_to_hass()
        self.async_on_remove(self.feed.async_add_listener(self.async_write_ha_state))

    @property
    def _family(self) -> str:
        info = self.live.info
        return chip_family(info.chip_family, info.chip)

    def _offer(self) -> FeedChannel | None:
        """The feed's channel entry when it is an update this robot can install."""
        info = self.live.info
        channel = (self.feed.data or {}).get(robot_channel(info.channel, info.version))
        if (
            channel is None
            or self._family not in channel.ota
            or not is_newer(channel.version, info.version)
        ):
            return None
        return channel

    @property
    def installed_version(self) -> str | None:
        """The firmware the robot runs."""
        return self.live.info.version or None

    @property
    def latest_version(self) -> str | None:
        """The feed's version when newer, else the installed one."""
        offer = self._offer()
        return offer.version if offer is not None else self.installed_version

    @property
    def release_summary(self) -> str | None:
        """The release's pitch, from the feed."""
        offer = self._offer()
        return offer.summary if offer is not None else None

    @property
    def release_url(self) -> str | None:
        """The release's notes on GitHub."""
        offer = self._offer()
        return offer.notes if offer is not None else None

    async def async_release_notes(self) -> str | None:
        """The release's pitch, with a link to its full notes."""
        offer = self._offer()
        if offer is None:
            return None
        parts = [offer.summary or ""]
        if offer.notes:
            parts.append(f"[Release notes]({offer.notes})")
        return "\n\n".join(part for part in parts if part) or None

    @callback
    def _progress(self, percentage: int) -> None:
        if percentage != self._attr_update_percentage:
            self._attr_update_percentage = percentage
            self.async_write_ha_state()

    async def async_install(self, version: str | None, backup: bool, **kwargs: Any) -> None:
        """Download the image, upload it to the robot, wait for it to come back."""
        state = self.live.state
        if state is not None and state.activity in BUSY_ACTIVITIES:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="update_busy"
            )
        offer = self._offer()
        if offer is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="update_not_available"
            )
        self._attr_in_progress = True
        self._attr_update_percentage = None
        self._progress(0)
        try:
            await self._install(offer)
        finally:
            self._attr_in_progress = False
            self._attr_update_percentage = None
            self.async_write_ha_state()

    async def _install(self, offer: FeedChannel) -> None:
        try:
            image = await async_download(
                self.hass,
                offer.ota[self._family],
                lambda got, total: self._progress(DOWNLOAD_END * got // total),
            )
        except DownloadFailed as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="update_download_failed"
            ) from err

        live = self.live
        previous = live.info.version
        connections = live.connections
        await self._command(
            live.client.update_firmware(
                image,
                lambda sent, total: self._progress(
                    DOWNLOAD_END + (UPLOAD_END - DOWNLOAD_END) * sent // total
                ),
            )
        )

        def back() -> bool:
            return (
                live.connected
                and live.connections > connections
                and live.info.version != previous
            )

        try:
            async with asyncio.timeout(RESTART_TIMEOUT):
                await asyncio.sleep(RESTART_GRACE)
                if live.connections == connections:
                    live.async_reconnect()
                await live.async_wait_for(back)
        except TimeoutError:
            if live.connected and live.connections > connections:
                # Back, but still on the old firmware: the new one didn't boot.
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="update_not_applied",
                    translation_placeholders={"version": previous},
                ) from None
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="update_no_restart"
            ) from None
