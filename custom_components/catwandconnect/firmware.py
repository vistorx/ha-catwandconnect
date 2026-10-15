"""The Update feed: which firmware each Update channel offers.

The CatWandConnect flasher site on GitHub Pages publishes `channels.json`
(https://vistorx.github.io/CatWandConnect/flasher/channels.json) with, per
Update channel, the latest version, its release notes and the OTA image of each
chip family. One `FeedCoordinator` reads it for every robot, at startup and
every 6 hours. When the feed can't be read, or is the older one without OTA
images, robots are simply offered no update.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util.hass_dict import HassKey

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Base URL of the flasher site; the feed's `ota` paths are relative to it.
FEED_URL = "https://vistorx.github.io/CatWandConnect/flasher/"
FEED_INTERVAL = timedelta(hours=6)
FEED_TIMEOUT = aiohttp.ClientTimeout(total=30)
# An OTA image is about 1.5 MB, from a CDN.
DOWNLOAD_TIMEOUT = aiohttp.ClientTimeout(total=300, sock_connect=30)
DOWNLOAD_CHUNK = 16 * 1024

CHANNELS = ("stable", "beta")
CHIP_FAMILIES = ("ESP32", "ESP32-S3", "ESP32-C3")

DATA_FEED: HassKey[FeedCoordinator] = HassKey(f"{DOMAIN}_feed")

_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+.*)?$")


@dataclass(frozen=True)
class FeedChannel:
    """One Update channel of the feed."""

    version: str
    notes: str | None = None
    summary: str | None = None
    # Chip family -> image path relative to FEED_URL; empty in the older feed.
    ota: dict[str, str] = field(default_factory=dict)


class DownloadFailed(Exception):
    """The OTA image could not be downloaded."""


def _key(version: str) -> tuple | None:
    """Sort key following semver precedence, or None for a non-version."""
    match = _VERSION.match(version.strip())
    if match is None:
        return None
    major, minor, patch, pre = match.groups()
    release = (int(major), int(minor), int(patch))
    if pre is None:
        # A release sorts after all its pre-releases.
        return (release, 1, ())
    identifiers = tuple(
        (0, int(part), "") if part.isdigit() else (1, 0, part) for part in pre.split(".")
    )
    return (release, 0, identifiers)


def is_newer(candidate: str, running: str) -> bool:
    """Whether `candidate` is strictly newer than `running` (semver, `v` stripped)."""
    new, old = _key(candidate), _key(running)
    return new is not None and old is not None and new > old


def robot_channel(channel: str | None, version: str) -> str:
    """The robot's Update channel; derived from its version on older firmware."""
    if channel in CHANNELS:
        return channel
    return "beta" if "-beta" in version else "stable"


def chip_family(family: str | None, chip: str | None) -> str:
    """The robot's chip family (the key into `ota`); derived from `chip` on older firmware."""
    if family in CHIP_FAMILIES:
        return family
    chip = (chip or "").upper()
    for candidate in ("ESP32-S3", "ESP32-C3"):
        if chip.startswith(candidate):
            return candidate
    return "ESP32"


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def parse_feed(body: Any) -> dict[str, FeedChannel]:
    """The channels of `channels.json`; anything malformed is left out."""
    channels: dict[str, FeedChannel] = {}
    if not isinstance(body, dict):
        return channels
    for name, raw in body.items():
        if not isinstance(raw, dict) or _text(raw.get("version")) is None:
            continue
        ota = raw.get("ota")
        channels[name] = FeedChannel(
            version=raw["version"],
            notes=_text(raw.get("notes")),
            summary=_text(raw.get("summary")),
            ota={
                family: path
                for family, path in (ota.items() if isinstance(ota, dict) else ())
                if isinstance(family, str) and _text(path)
            },
        )
    return channels


class FeedCoordinator(DataUpdateCoordinator[dict[str, FeedChannel]]):
    """Reads the Update feed for all robots."""

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=None,
            name=f"{DOMAIN} Update feed",
            update_interval=FEED_INTERVAL,
        )

    async def _async_update_data(self) -> dict[str, FeedChannel]:
        """The feed's channels; none when it can't be read (logged at debug only)."""
        session = async_get_clientsession(self.hass)
        url = f"{FEED_URL}channels.json"
        try:
            async with session.get(url, timeout=FEED_TIMEOUT) as resp:
                resp.raise_for_status()
                body = await resp.json(content_type=None)
        except (OSError, aiohttp.ClientError, ValueError) as err:
            _LOGGER.debug("Update feed %s unreadable: %s", url, err)
            return {}
        channels = parse_feed(body)
        _LOGGER.debug(
            "Update feed: %s",
            {name: channel.version for name, channel in channels.items()},
        )
        return channels


@callback
def async_get_feed(hass: HomeAssistant) -> FeedCoordinator:
    """The shared feed coordinator; the first call starts reading the feed.

    The read runs in the background so a slow or missing internet connection
    never delays the robots' setup; entities follow the coordinator.
    """
    coordinator = hass.data.get(DATA_FEED)
    if coordinator is None:
        coordinator = hass.data[DATA_FEED] = FeedCoordinator(hass)
        hass.async_create_background_task(
            coordinator.async_refresh(), f"{DOMAIN} Update feed first read"
        )
    return coordinator


async def async_download(
    hass: HomeAssistant, path: str, progress: Callable[[int, int], None]
) -> bytes:
    """Download a file of the flasher site, reporting (received, total) bytes."""
    session = async_get_clientsession(hass)
    try:
        async with session.get(f"{FEED_URL}{path}", timeout=DOWNLOAD_TIMEOUT) as resp:
            resp.raise_for_status()
            total = resp.content_length or 0
            data = bytearray()
            async for chunk in resp.content.iter_chunked(DOWNLOAD_CHUNK):
                data.extend(chunk)
                progress(len(data), max(total, len(data)))
    except (OSError, aiohttp.ClientError) as err:
        raise DownloadFailed(str(err)) from err
    if not data:
        raise DownloadFailed("empty file")
    return bytes(data)
