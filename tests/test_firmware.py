"""Version rule, Update channel and chip family, and the Update feed's shape."""

from __future__ import annotations

import pytest

from custom_components.catwandconnect.firmware import (
    chip_family,
    is_newer,
    parse_feed,
    robot_channel,
)

from .fake_feed import channel, old_feed


@pytest.mark.parametrize(
    ("candidate", "running", "newer"),
    [
        ("0.2.0", "0.1.0", True),
        ("0.2.0-beta.10", "0.2.0-beta.3", True),
        ("0.2.0", "0.2.0-beta.10", True),
        ("0.2.0-beta.3", "0.2.0", False),
        ("0.2.0", "0.2.0", False),
        ("v0.2.1", "0.2.0", True),
        ("0.10.0", "0.9.9", True),
        ("0.2.0-beta.3", "0.2.0-beta.3", False),
        ("0.2.0-rc.1", "0.2.0-beta.9", True),
        ("0.2.0-beta.2", "0.2.0-beta", True),
        # A beta robot on the Stable channel is not offered an older stable.
        ("0.1.0", "0.2.0-beta.3", False),
        ("garbage", "0.1.0", False),
        ("0.2.0", "", False),
    ],
)
def test_version_rule(candidate: str, running: str, newer: bool) -> None:
    assert is_newer(candidate, running) is newer


@pytest.mark.parametrize(
    ("channel_field", "version", "expected"),
    [
        ("stable", "0.2.0-beta.3", "stable"),
        ("beta", "0.2.0", "beta"),
        (None, "0.2.0-beta.3", "beta"),
        (None, "0.2.0", "stable"),
        ("", "0.2.0-beta.3", "beta"),
    ],
)
def test_channel_from_info_or_version(
    channel_field: str | None, version: str, expected: str
) -> None:
    assert robot_channel(channel_field, version) == expected


@pytest.mark.parametrize(
    ("family", "chip", "expected"),
    [
        ("ESP32-S3", "ESP32-D0WD-V3", "ESP32-S3"),
        (None, "ESP32-D0WD-V3", "ESP32"),
        (None, "ESP32-S3", "ESP32-S3"),
        (None, "ESP32-C3", "ESP32-C3"),
        (None, None, "ESP32"),
    ],
)
def test_chip_family_from_info_or_chip(
    family: str | None, chip: str | None, expected: str
) -> None:
    assert chip_family(family, chip) == expected


def test_extended_feed_is_parsed() -> None:
    feed = parse_feed({"stable": channel("0.2.0", "Faster."), "beta": channel("0.3.0-beta.1")})
    stable = feed["stable"]
    assert stable.version == "0.2.0"
    assert stable.summary == "Faster."
    assert stable.notes == "https://github.com/vistorx/CatWandConnect/releases/tag/v0.2.0"
    assert stable.ota["ESP32-C3"] == "stable/catwandconnect-esp32c3-ota.bin"


def test_old_feed_has_versions_but_no_images() -> None:
    feed = parse_feed(old_feed())
    assert feed["beta"].version == "0.2.0-beta.3"
    assert feed["beta"].ota == {}
    assert feed["beta"].notes is None


@pytest.mark.parametrize("body", [None, [], "x", {"stable": "0.2.0"}, {"stable": {"tag": "v1"}}])
def test_malformed_feed_has_no_channels(body) -> None:
    assert parse_feed(body) == {}
