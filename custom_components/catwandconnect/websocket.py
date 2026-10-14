"""Home Assistant websocket commands driving the wand, for the joystick card.

The card runs in the owner's browser, which may not reach the robot, so it
sends `catwandconnect/move` and `catwandconnect/stop` to Home Assistant, and
each one is forwarded over the robot's existing /ws connection. The card
resends `move` every 100 ms while the finger is down; nothing here repeats it,
so the robot's dead-man rule (no `move` for 500 ms → stop) still applies when a
browser closes or loses the network.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr

from .api import RobotError
from .const import DOMAIN
from .live import RobotLive

CONF_DEVICE_ID = "device_id"
CONF_ENTRY_ID = "entry_id"

_ROBOT = {
    vol.Exclusive(CONF_DEVICE_ID, "robot"): str,
    vol.Exclusive(CONF_ENTRY_ID, "robot"): str,
}


def _deflection(value: Any) -> float:
    """A joystick deflection in [-1, 1]; numbers outside are capped."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise vol.Invalid("expected a number")
    return max(-1.0, min(1.0, float(value)))


@callback
def async_register(hass: HomeAssistant) -> None:
    """Register the commands once for the whole integration."""
    websocket_api.async_register_command(hass, ws_move)
    websocket_api.async_register_command(hass, ws_stop)


def _live(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> RobotLive | None:
    """The robot the message names, or None after sending the error."""
    entry_id = msg.get(CONF_ENTRY_ID)
    if CONF_DEVICE_ID in msg:
        device = dr.async_get(hass).async_get(msg[CONF_DEVICE_ID])
        entry_id = next(
            (
                e
                for e in (device.config_entries if device else ())
                if (entry := hass.config_entries.async_get_entry(e))
                and entry.domain == DOMAIN
            ),
            None,
        )
    elif entry_id is None:
        connection.send_error(
            msg["id"],
            websocket_api.ERR_INVALID_FORMAT,
            "Give the robot's device_id or entry_id",
        )
        return None

    entry = hass.config_entries.async_get_entry(entry_id) if entry_id else None
    if entry is None or entry.domain != DOMAIN:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "No such robot")
        return None
    if entry.state is not ConfigEntryState.LOADED or not entry.runtime_data.connected:
        connection.send_error(
            msg["id"], "not_connected", f"{entry.title} is not connected"
        )
        return None
    return entry.runtime_data


async def _forward(
    connection: websocket_api.ActiveConnection, msg: dict[str, Any], frame: Any
) -> None:
    try:
        await frame
    except RobotError as err:
        connection.send_error(msg["id"], "not_connected", str(err))
        return
    connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/move",
        **_ROBOT,
        vol.Required("h"): _deflection,
        vol.Required("v"): _deflection,
    }
)
@websocket_api.async_response
async def ws_move(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Manual control: move the wand at fractions `h`, `v` of its maximum speed."""
    if (live := _live(hass, connection, msg)) is not None:
        await _forward(connection, msg, live.async_move(msg["h"], msg["v"]))


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/stop", **_ROBOT})
@websocket_api.async_response
async def ws_stop(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """End Manual control: the wand decelerates and stops."""
    if (live := _live(hass, connection, msg)) is not None:
        await _forward(connection, msg, live.async_stop())
