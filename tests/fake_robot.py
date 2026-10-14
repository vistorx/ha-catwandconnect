"""A fake CatWandConnect robot speaking the documented Device API.

It is the single test seam of the integration: tests talk to it over real
HTTP and WebSocket, exactly as the integration talks to a robot. Only the parts
of https://vistorx.github.io/CatWandConnect/api/ the integration uses are
implemented, with the same status codes and JSON shapes.

Configurable per test: Settings PIN on or off, API version (``None`` for a
firmware too old to report one), Calibration, a busy robot, and a disconnect
that closes every WebSocket client.
"""

from __future__ import annotations

import asyncio
import math
import secrets
from dataclasses import dataclass, field
from typing import Any

from aiohttp import WSMsgType, web
from aiohttp.test_utils import TestServer

AXES = ("horizontal", "vertical")
ACTIVITIES = ("idle", "manual", "stowing", "calibrating", "tuning_speed", "playing")
MAX_PIN_ATTEMPTS = 5
FIRST_LOCKOUT_S = 30
MAX_LOCKOUT_S = 15 * 60


def _default_axes() -> dict[str, dict[str, float]]:
    return {
        "horizontal": {
            "min": 60, "max": 120, "stow": 90, "maxSpeed": 90, "minSpeed": 9,
            "maxAccel": 360, "pauseMin": 0.5, "pauseMax": 3,
        },
        "vertical": {
            "min": 60, "max": 120, "stow": 90, "maxSpeed": 90, "minSpeed": 9,
            "maxAccel": 360, "pauseMin": 1, "pauseMax": 5,
        },
    }


@dataclass
class FakeRobot:
    """State and behaviour of one fake robot."""

    name: str = "CatWandConnect"
    hostname: str = "catwandconnect.local"
    version: str = "0.2.0"
    chip: str = "ESP32-D0WD-V3"
    api: int | None = 1
    device_id: str = "3f9a1c2b7d4e6f80"
    pin: str | None = None
    calibrated: bool = True
    activity: str = "idle"
    h: float = 90.0
    v: float = 90.0
    play_speed: float = 0.6
    session_minutes: int = 10
    play_remaining: int = 0
    axes: dict[str, dict[str, float]] = field(default_factory=_default_axes)

    offline: bool = False
    ws_connections: int = 0
    tokens: set[str] = field(default_factory=set)
    failed_unlocks: int = 0
    locked_for: int = 0
    requests: list[tuple[str, str]] = field(default_factory=list)
    _clients: set[web.WebSocketResponse] = field(default_factory=set)
    _server: TestServer | None = None

    # ------------------------------------------------------------------ server

    def app(self) -> web.Application:
        app = web.Application(middlewares=[self._log_middleware])
        app.router.add_get("/api/info", self._info)
        app.router.add_get("/api/auth", self._auth)
        app.router.add_post("/api/auth/unlock", self._unlock)
        app.router.add_get("/api/play", self._get_play)
        app.router.add_post("/api/play", self._post_play)
        app.router.add_post("/api/stow", self._stow)
        app.router.add_post("/api/position", self._position)
        app.router.add_get("/api/settings", self._get_settings)
        app.router.add_put("/api/settings", self._put_settings)
        app.router.add_get("/ws", self._ws)
        return app

    async def start(self) -> None:
        self._server = TestServer(self.app(), host="127.0.0.1")
        await self._server.start_server()

    async def close(self) -> None:
        await self.disconnect()
        if self._server is not None:
            await self._server.close()
            self._server = None

    @property
    def host(self) -> str:
        assert self._server is not None, "robot not started"
        return f"127.0.0.1:{self._server.port}"

    @property
    def url(self) -> str:
        return f"http://{self.host}"

    @property
    def ws_clients(self) -> int:
        return len(self._clients)

    async def disconnect(self) -> None:
        """Drop every WebSocket client, as when the robot leaves Wi-Fi."""
        for ws in list(self._clients):
            await ws.close()
        self._clients.clear()

    async def go_offline(self) -> None:
        """Leave the network: drop the sockets and refuse every request."""
        self.offline = True
        await self.disconnect()

    def go_online(self) -> None:
        """Come back: answer requests and accept sockets again."""
        self.offline = False

    # ------------------------------------------------------------------ state

    def state(self) -> dict[str, Any]:
        msg: dict[str, Any] = {
            "t": "state",
            "h": self.h,
            "v": self.v,
            "activity": self.activity,
            "held": self.activity != "idle",
            "playSpeed": self.play_speed,
            "calibrated": self.calibrated,
            "calibration": "none",
            "sessionMinutes": self.session_minutes,
            "name": self.name,
        }
        if self.activity == "playing":
            msg["play"] = {"remaining": self.play_remaining}
        return msg

    async def push_state(self) -> None:
        """Send the state to every WebSocket client, as on any change."""
        msg = self.state()
        for ws in list(self._clients):
            if ws.closed:
                self._clients.discard(ws)
                continue
            await ws.send_json(msg)

    async def set_activity(self, activity: str) -> None:
        """Change the activity from outside (joystick, screen) and push it."""
        assert activity in ACTIVITIES
        self.activity = activity
        if activity != "playing":
            self.play_remaining = 0
        await self.push_state()

    async def move(self, h: float | None = None, v: float | None = None) -> None:
        """Move the wand from outside (joystick) and push the state."""
        if h is not None:
            self.h = h
        if v is not None:
            self.v = v
        self.activity = "manual"
        self.play_remaining = 0
        await self.push_state()

    async def rename(self, name: str) -> None:
        """Rename the robot from its Device interface and push the state."""
        self.name = name
        await self.push_state()

    async def send_raw(self, data: str | bytes) -> None:
        """Send any frame to every WebSocket client (other message types)."""
        for ws in list(self._clients):
            if isinstance(data, bytes):
                await ws.send_bytes(data)
            else:
                await ws.send_str(data)

    # ------------------------------------------------------------------ helpers

    @web.middleware
    async def _log_middleware(self, request: web.Request, handler):
        self.requests.append((request.method, request.path))
        if self.offline:
            return self._error(503, "offline")
        return await handler(request)

    def _authorized(self, request: web.Request) -> bool:
        header = request.headers.get("Authorization", "")
        return header.startswith("Bearer ") and header[7:] in self.tokens

    def _pin_ok(self, request: web.Request) -> bool:
        return self.pin is None or self._authorized(request)

    @staticmethod
    def _error(status: int, code: str, **extra: Any) -> web.Response:
        return web.json_response({"error": code, **extra}, status=status)

    @staticmethod
    async def _json(request: web.Request) -> dict[str, Any] | None:
        try:
            body = await request.json()
        except ValueError:
            return None
        return body if isinstance(body, dict) else None

    def _play(self) -> dict[str, Any]:
        active = self.activity == "playing"
        return {
            "active": active,
            "remaining": self.play_remaining if active else 0,
            "minutes": self.session_minutes,
        }

    def _settings(self) -> dict[str, Any]:
        return {
            "playSpeed": self.play_speed,
            "calibrated": self.calibrated,
            "axes": {axis: dict(values) for axis, values in self.axes.items()},
            "sessionMinutes": self.session_minutes,
        }

    # ------------------------------------------------------------------ routes

    async def _info(self, request: web.Request) -> web.Response:
        info: dict[str, Any] = {
            "name": self.name,
            "hostname": self.hostname,
            "version": self.version,
            "chip": self.chip,
            "id": self.device_id,
        }
        if self.api is not None:
            info["api"] = self.api
        else:
            # Firmware older than API version 1 knows neither field.
            del info["id"]
        return web.json_response(info)

    async def _auth(self, request: web.Request) -> web.Response:
        return web.json_response(
            {
                "enabled": self.pin is not None,
                "authorized": self._authorized(request),
                "lockedFor": self.locked_for,
            }
        )

    async def _unlock(self, request: web.Request) -> web.Response:
        if self.locked_for > 0:
            return self._error(429, "locked_out", retryAfter=self.locked_for)
        body = await self._json(request)
        if body is None:
            return self._error(400, "invalid_json")
        if self.pin is not None and body.get("pin") != self.pin:
            self.failed_unlocks += 1
            if self.failed_unlocks >= MAX_PIN_ATTEMPTS:
                doublings = self.failed_unlocks - MAX_PIN_ATTEMPTS
                self.locked_for = min(FIRST_LOCKOUT_S * 2**doublings, MAX_LOCKOUT_S)
            return self._error(401, "wrong_pin")
        self.failed_unlocks = 0
        token = secrets.token_hex(16)
        self.tokens.add(token)
        return web.json_response({"token": token})

    async def _get_play(self, request: web.Request) -> web.Response:
        return web.json_response(self._play())

    async def _post_play(self, request: web.Request) -> web.Response:
        body = await self._json(request)
        if body is None:
            return self._error(400, "invalid_json")
        action = body.get("action")
        if action == "stop":
            if self.activity == "playing":
                self.activity = "stowing"
                self.play_remaining = 0
                await self.push_state()
            return web.json_response(self._play())
        if action != "start":
            return self._error(400, "invalid_request")
        if not self.calibrated:
            return self._error(409, "not_calibrated")
        if self.activity in ("stowing", "calibrating", "tuning_speed"):
            return self._error(409, "busy")
        if "sessionMinutes" in body:
            minutes = body["sessionMinutes"]
            if not isinstance(minutes, int) or not 1 <= minutes <= 60:
                return self._error(400, "session_duration_out_of_range")
            self.session_minutes = minutes
        self.activity = "playing"
        self.play_remaining = self.session_minutes * 60
        await self.push_state()
        return web.json_response(self._play())

    async def _stow(self, request: web.Request) -> web.Response:
        self.activity = "stowing"
        self.play_remaining = 0
        await self.push_state()
        return web.Response(status=202)

    async def _position(self, request: web.Request) -> web.Response:
        body = await self._json(request)
        if body is None:
            return self._error(400, "invalid_json")
        axis = body.get("axis")
        degrees = body.get("degrees")
        if (
            axis not in AXES
            or isinstance(degrees, bool)
            or not isinstance(degrees, (int, float))
            or not math.isfinite(degrees)
        ):
            return self._error(400, "invalid_request")
        if self.activity == "stowing":
            return web.json_response({"ok": True})
        limits = self.axes[axis] if self.calibrated else {"min": 60, "max": 120}
        clamped = max(limits["min"], min(limits["max"], float(degrees)))
        if axis == "horizontal":
            self.h = clamped
        else:
            self.v = clamped
        self.activity = "manual"
        self.play_remaining = 0
        await self.push_state()
        return web.json_response({"ok": True})

    async def _get_settings(self, request: web.Request) -> web.Response:
        return web.json_response(self._settings())

    async def _put_settings(self, request: web.Request) -> web.Response:
        body = await self._json(request)
        if body is None:
            return self._error(400, "invalid_json")
        if not set(body) <= {"playSpeed", "sessionMinutes"} and not self._pin_ok(request):
            return self._error(401, "pin_required")
        if "sessionMinutes" in body:
            minutes = body["sessionMinutes"]
            if not isinstance(minutes, int) or not 1 <= minutes <= 60:
                return self._error(400, "session_duration_out_of_range")
        for axis in AXES:
            speed = body.get("axes", {}).get(axis, {}).get("maxSpeed")
            if speed is not None and not 10 <= speed <= 360:
                return self._error(400, "speed_out_of_range", axis=axis)
        if "sessionMinutes" in body:
            self.session_minutes = body["sessionMinutes"]
        if "playSpeed" in body:
            self.play_speed = body["playSpeed"]
        for axis, values in body.get("axes", {}).items():
            if axis in AXES:
                self.axes[axis].update(values)
        await self.push_state()
        return web.json_response(self._settings())

    async def _ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self._clients.add(ws)
        self.ws_connections += 1
        try:
            await ws.send_json(self.state())
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                data = msg.json()
                if data.get("t") == "stow":
                    self.activity = "stowing"
                    self.play_remaining = 0
                    await self.push_state()
        except (asyncio.CancelledError, ConnectionResetError):
            pass
        finally:
            self._clients.discard(ws)
        return ws
