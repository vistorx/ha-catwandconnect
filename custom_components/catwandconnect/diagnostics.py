"""Diagnostics download for bug reports, with personal data redacted.

Redacts what the robot's own Diagnostic report hides (Wi-Fi name, IP and MAC
addresses, broker address and credentials, a custom name and hostname) plus the
Settings PIN and session token. The Device ID stays: it is random and not
personal, so support can group the reports of one robot.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import CatWandConnectConfigEntry
from .api import RobotError

TO_REDACT = {
    # Settings PIN and session token
    "pin",
    "token",
    "password",
    # Network: Wi-Fi name, addresses, names that identify the home
    "host",
    "hostname",
    "ssid",
    "ip",
    "mac",
    "name",
    # MQTT broker address and credentials
    "broker",
    "user",
    "username",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: CatWandConnectConfigEntry
) -> dict[str, Any]:
    """Entry data, /api/info, /api/settings and the last /ws state, redacted."""
    live = entry.runtime_data
    client = live.client
    data: dict[str, Any] = {
        "entry": dict(entry.data),
        "connected": live.connected,
        "state": asdict(live.state) if live.state is not None else None,
    }
    for key, path in (("info", "/api/info"), ("settings", "/api/settings")):
        try:
            data[key] = await client.raw(path)
        except RobotError:
            data[key] = {"error": "unreachable"}
    return async_redact_data(data, TO_REDACT)
