"""Live state of one robot over its /ws connection.

One `RobotLive` per config entry owns the robot's WebSocket: it connects,
receives each pushed state and tells the entities. While the socket is down the
entities are unavailable, and it reconnects with a growing delay. After each
(re)connection it reads GET /api/info again (the firmware version may have
changed: a Firmware update restarts the robot), and after each (re)connection
and when Calibration or Speed tuning ends, GET /api/settings for the Travel
limits and maximum speeds, which the state messages don't carry.

On each connection it also says hello (so the robot's Play session journal
credits Home Assistant's commands) and, when the firmware keeps the journal,
gives the robot Home Assistant's time: the robot has no other clock than the
browser's and Home Assistant's (CatWandConnect ADR 0013). Journal events are
passed on to the event entity as they come; old ones are never replayed.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util

from .api import (
    CannotConnect,
    CatWandConnectClient,
    JournalEvent,
    RobotError,
    RobotInfo,
    RobotSettings,
    RobotSocket,
    RobotState,
)
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Seconds to wait before each reconnection attempt; the last one repeats.
RECONNECT_DELAYS: tuple[float, ...] = (1, 2, 5, 10, 30)

# Activities whose end may have changed the settings the entities show.
_SETTINGS_ACTIVITIES = ("calibrating", "tuning_speed")


class RobotLive:
    """Owns the /ws connection of one robot and its latest state."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: CatWandConnectClient,
        device_id: str,
        info: RobotInfo,
        has_journal: bool = False,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.client = client
        self.device_id = device_id
        self.info = info
        # Counts the connections; a new value means the robot came back.
        self.connections = 0
        self.state: RobotState | None = None
        self.settings: RobotSettings | None = None
        # Whether the firmware keeps the Play session journal; the entities
        # that need it are only created when it does.
        self.has_journal = has_journal
        self._listeners: list[CALLBACK_TYPE] = []
        self._event_listeners: list[Callable[[JournalEvent], None]] = []
        self._socket: RobotSocket | None = None
        self._task: asyncio.Task[None] | None = None

    @property
    def connected(self) -> bool:
        """Whether the socket is up and the state and settings are known."""
        return (
            self._socket is not None
            and self.state is not None
            and self.settings is not None
        )

    @callback
    def async_add_listener(self, update: CALLBACK_TYPE) -> Callable[[], None]:
        """Call `update` on every change; returns a function that stops it."""
        self._listeners.append(update)
        return lambda: self._listeners.remove(update)

    @callback
    def async_add_event_listener(
        self, on_event: Callable[[JournalEvent], None]
    ) -> Callable[[], None]:
        """Call `on_event` for each new Play session journal event."""
        self._event_listeners.append(on_event)
        return lambda: self._event_listeners.remove(on_event)

    @callback
    def _notify(self) -> None:
        for update in list(self._listeners):
            update()

    @callback
    def apply_settings(self, settings: RobotSettings) -> None:
        """Show settings the robot just answered with (state messages lack them)."""
        self.settings = settings
        self._notify()

    @callback
    def start(self) -> None:
        """Start connecting in the background."""
        self._task = self.entry.async_create_background_task(
            self.hass, self._run(), f"{DOMAIN} {self.client.host} /ws"
        )

    @callback
    def async_reconnect(self) -> None:
        """Drop the socket so it reconnects (after a restart it may look alive)."""
        if self._socket is not None:
            self.hass.async_create_task(self._socket.close())

    async def async_wait_for(self, condition: Callable[[], bool]) -> None:
        """Wait until `condition` holds, checked on every change."""
        if condition():
            return
        done = asyncio.Event()

        @callback
        def check() -> None:
            if condition():
                done.set()

        remove = self.async_add_listener(check)
        try:
            await done.wait()
        finally:
            remove()

    async def stop(self) -> None:
        """Close the socket and stop reconnecting."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def async_move(self, h: float, v: float) -> None:
        """Manual control: move at fractions `h`, `v` of the maximum speed.

        The robot stops by itself unless another move follows within 500 ms.
        """
        await self._send({"t": "move", "h": h, "v": v})

    async def async_stop(self) -> None:
        """End Manual control: the wand decelerates and stops."""
        await self._send({"t": "stop"})

    async def _send(self, frame: dict[str, Any]) -> None:
        if self._socket is None:
            raise CannotConnect("not connected")
        await self._socket.send(frame)

    async def _run(self) -> None:
        attempt = 0
        while True:
            try:
                await self._session()
                attempt = 0
            except RobotError as err:
                _LOGGER.debug("Robot at %s: %s", self.client.host, err)
            delay = RECONNECT_DELAYS[min(attempt, len(RECONNECT_DELAYS) - 1)]
            attempt += 1
            await asyncio.sleep(delay)

    async def _open(self) -> RobotSocket:
        """Open the socket; if cancelled meanwhile, close it once it's open.

        Cancelling aiohttp's ws_connect halfway can leave an open connection
        behind, so the handshake is shielded and finished before giving up.
        """
        opening = asyncio.ensure_future(self.client.socket())
        try:
            return await asyncio.shield(opening)
        except asyncio.CancelledError:
            try:
                socket = await opening
            except RobotError:
                pass
            else:
                await socket.close()
            raise

    async def _session(self) -> None:
        """One connection, from opening the socket until it drops."""
        socket = await self._open()
        self._socket = socket
        try:
            self._follow_info(await self.client.info())
            self.settings = await self.client.settings()
            await self._introduce(socket)
            self.connections += 1
            async for message in socket:
                if isinstance(message, JournalEvent):
                    for on_event in list(self._event_listeners):
                        on_event(message)
                else:
                    await self._on_state(message)
            _LOGGER.debug("Robot at %s closed the socket", self.client.host)
        finally:
            self._socket = None
            self.state = None
            await socket.close()
            self._notify()

    async def _introduce(self, socket: RobotSocket) -> None:
        """Say who we are and, if the robot keeps a journal, what time it is."""
        await socket.send({"t": "hello", "client": "home_assistant"})
        if not self.has_journal:
            # An update may have brought the journal: reload to add its entities.
            if await self.client.has_journal():
                _LOGGER.debug("Robot at %s now keeps a Play session journal", self.client.host)
                self.hass.config_entries.async_schedule_reload(self.entry.entry_id)
            return
        now = dt_util.now()
        offset = now.utcoffset()
        try:
            await self.client.set_time(
                int(time.time() * 1000),
                int(offset.total_seconds() // 60) if offset is not None else 0,
                self.hass.config.time_zone or "",
            )
        except RobotError as err:
            # Only the journal's dates and Sessions today suffer: carry on.
            _LOGGER.debug("Robot at %s: could not set its clock: %s", self.client.host, err)

    async def _on_state(self, state: RobotState) -> None:
        previous = self.state
        self.state = state
        if previous is not None and (
            previous.calibrated != state.calibrated
            or (
                previous.activity in _SETTINGS_ACTIVITIES
                and state.activity != previous.activity
            )
        ):
            self.settings = await self.client.settings()
        if state.name is not None:
            self._follow_name(state.name)
        self._notify()

    @callback
    def _follow_info(self, info: RobotInfo) -> None:
        """Keep the robot's info, and the device's firmware version, current."""
        self.info = info
        registry = dr.async_get(self.hass)
        device = registry.async_get_device_by_identifier(
            (DOMAIN, self.device_id), self.entry.entry_id
        )
        if device is not None and device.sw_version != info.version:
            registry.async_update_device(device.id, sw_version=info.version)

    @callback
    def _follow_name(self, name: str) -> None:
        """Rename the device and entry after the robot, keeping a user's name."""
        registry = dr.async_get(self.hass)
        device = registry.async_get_device_by_identifier(
            (DOMAIN, self.device_id), self.entry.entry_id
        )
        if device is not None and device.name != name:
            registry.async_update_device(device.id, name=name)
        if self.entry.title != name:
            self.hass.config_entries.async_update_entry(self.entry, title=name)
