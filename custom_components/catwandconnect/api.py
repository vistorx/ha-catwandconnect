"""Async client for a CatWandConnect robot's Device API.

The only module that knows the robot's URLs and JSON shapes
(https://vistorx.github.io/CatWandConnect/api/).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any

import aiohttp

TIMEOUT = aiohttp.ClientTimeout(total=10)
# A firmware image is about 1.5 MB, written to flash as it arrives over Wi-Fi.
UPDATE_TIMEOUT = aiohttp.ClientTimeout(total=600, sock_connect=10)
UPLOAD_CHUNK = 8 * 1024

AXES = ("horizontal", "vertical")
ACTIVITIES = ("idle", "manual", "stowing", "calibrating", "tuning_speed", "playing")


class RobotError(Exception):
    """Base error talking to a robot."""


class CannotConnect(RobotError):
    """The robot can't be reached or answered something unexpected."""


class WrongPin(RobotError):
    """The Settings PIN was refused."""


class PinRequired(RobotError):
    """A PIN-protected request was refused and no PIN is stored to unlock."""


class Refused(RobotError):
    """The robot refused a command; `code` is its error code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class LockedOut(RobotError):
    """Too many wrong PINs: unlocking is refused for a while."""

    def __init__(self, retry_after: int) -> None:
        super().__init__(f"locked out for {retry_after} s")
        self.retry_after = retry_after


@dataclass(frozen=True)
class RobotInfo:
    """What GET /api/info says about the robot."""

    name: str
    version: str
    chip: str | None
    api: int | None
    device_id: str | None
    # Update channel and chip family; None on firmware older than the Update feed.
    channel: str | None = None
    chip_family: str | None = None


@dataclass(frozen=True)
class AuthState:
    """What GET /api/auth says about the Settings PIN."""

    enabled: bool
    authorized: bool
    locked_for: int


@dataclass(frozen=True)
class AxisSettings:
    """The settings of one Axis the integration shows."""

    min: float
    max: float
    max_speed: float
    min_speed: float


@dataclass(frozen=True)
class RobotSettings:
    """What GET /api/settings says, as far as the integration uses it."""

    calibrated: bool
    axes: dict[str, AxisSettings]
    session_minutes: int


@dataclass(frozen=True)
class RobotState:
    """One state message pushed on /ws."""

    h: float | None
    v: float | None
    activity: str | None
    calibrated: bool
    session_minutes: int | None
    name: str | None
    # Seconds left in the Play session, rounded up; None when no session
    # runs or the firmware doesn't say.
    play_remaining: int | None = None


class _ImagePayload(aiohttp.BytesPayload):
    """A firmware image sent in chunks, reporting the bytes sent so far."""

    def __init__(self, image: bytes, progress: Callable[[int, int], None]) -> None:
        super().__init__(image, content_type="application/octet-stream")
        self._image = image
        self._progress = progress

    async def write(self, writer: Any) -> None:
        await self.write_with_length(writer, None)

    async def write_with_length(self, writer: Any, content_length: int | None) -> None:
        image = self._image if content_length is None else self._image[:content_length]
        for start in range(0, len(image), UPLOAD_CHUNK):
            await writer.write(image[start : start + UPLOAD_CHUNK])
            self._progress(min(start + UPLOAD_CHUNK, len(image)), len(image))


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


class RobotSocket:
    """An open /ws connection: iterate it to receive the robot's states."""

    def __init__(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        self._ws = ws

    async def send(self, frame: dict[str, Any]) -> None:
        """Send one message to the robot."""
        try:
            await self._ws.send_json(frame)
        except (ConnectionError, aiohttp.ClientError) as err:
            raise CannotConnect(str(err)) from err

    async def close(self) -> None:
        """Close the connection."""
        await self._ws.close()
        # aiohttp re-arms the heartbeat timer when a frame arrives while
        # closing; drop it so no timer outlives the connection.
        cancel_heartbeat = getattr(self._ws, "_cancel_heartbeat", None)
        if cancel_heartbeat is not None:
            cancel_heartbeat()

    async def __aiter__(self) -> AsyncIterator[RobotState]:
        """Yield each state message until the robot closes the connection."""
        async for msg in self._ws:
            if msg.type is aiohttp.WSMsgType.ERROR:
                raise CannotConnect(str(self._ws.exception()))
            if msg.type is not aiohttp.WSMsgType.TEXT:
                continue
            try:
                data = msg.json()
            except ValueError:
                continue
            if not isinstance(data, dict) or data.get("t") != "state":
                continue
            activity = data.get("activity")
            name = data.get("name")
            minutes = data.get("sessionMinutes")
            play = data.get("play")
            remaining = play.get("remaining") if isinstance(play, dict) else None
            yield RobotState(
                h=_number(data.get("h")),
                v=_number(data.get("v")),
                activity=activity if isinstance(activity, str) else None,
                calibrated=bool(data.get("calibrated")),
                session_minutes=minutes if isinstance(minutes, int) else None,
                name=name if isinstance(name, str) and name else None,
                play_remaining=remaining
                if isinstance(remaining, int) and not isinstance(remaining, bool)
                else None,
            )


class CatWandConnectClient:
    """Talks to one robot over HTTP."""

    def __init__(
        self, session: aiohttp.ClientSession, host: str, pin: str = ""
    ) -> None:
        self._session = session
        self.host = host
        self.pin = pin
        self.token: str | None = None

    @property
    def url(self) -> str:
        """Base URL of the robot's Device interface."""
        return f"http://{self.host}"

    async def _request(
        self,
        method: str,
        path: str,
        json: Any = None,
        data: Callable[[], Any] | None = None,
        timeout: aiohttp.ClientTimeout = TIMEOUT,
    ) -> tuple[int, Any]:
        """Send one request; `data` builds a fresh body for each attempt."""
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else None
        try:
            async with self._session.request(
                method,
                f"{self.url}{path}",
                json=json,
                data=data() if data is not None else None,
                headers=headers,
                timeout=timeout,
            ) as resp:
                try:
                    body = await resp.json(content_type=None)
                except ValueError:
                    body = None
                return resp.status, body
        except (TimeoutError, aiohttp.ClientError) as err:
            raise CannotConnect(str(err)) from err

    async def _get_object(self, path: str) -> dict[str, Any]:
        status, body = await self._request("GET", path)
        if status != 200 or not isinstance(body, dict):
            raise CannotConnect(f"GET {path} answered {status}")
        return body

    async def raw(self, path: str) -> dict[str, Any]:
        """Read a GET endpoint as the robot sends it (for diagnostics)."""
        return await self._get_object(path)

    async def info(self) -> RobotInfo:
        """Read the robot's identity and API version."""
        body = await self._get_object("/api/info")
        api = body.get("api")
        channel = body.get("channel")
        family = body.get("chipFamily")
        return RobotInfo(
            name=str(body.get("name") or "CatWandConnect"),
            version=str(body.get("version", "")),
            chip=body.get("chip"),
            api=api if isinstance(api, int) and not isinstance(api, bool) else None,
            device_id=body.get("id"),
            channel=channel if isinstance(channel, str) and channel else None,
            chip_family=family if isinstance(family, str) and family else None,
        )

    async def auth(self) -> AuthState:
        """Read whether the Settings PIN is on."""
        body = await self._get_object("/api/auth")
        return AuthState(
            enabled=bool(body.get("enabled")),
            authorized=bool(body.get("authorized")),
            locked_for=int(body.get("lockedFor") or 0),
        )

    async def settings(self) -> RobotSettings:
        """Read the Travel limits, maximum speeds and Session duration."""
        return self._parse_settings(await self._get_object("/api/settings"))

    @staticmethod
    def _parse_settings(body: dict[str, Any]) -> RobotSettings:
        axes: dict[str, AxisSettings] = {}
        raw_axes = body.get("axes")
        for axis in AXES:
            raw = raw_axes.get(axis) if isinstance(raw_axes, dict) else None
            values = [
                _number(raw.get(key)) if isinstance(raw, dict) else None
                for key in ("min", "max", "maxSpeed", "minSpeed")
            ]
            if None in values:
                raise CannotConnect(f"settings: no {axis} axis")
            axes[axis] = AxisSettings(*values)  # type: ignore[arg-type]
        minutes = body.get("sessionMinutes")
        return RobotSettings(
            calibrated=bool(body.get("calibrated")),
            axes=axes,
            session_minutes=minutes if isinstance(minutes, int) else 0,
        )

    async def socket(self) -> RobotSocket:
        """Open the /ws connection the robot pushes its state on."""
        try:
            async with asyncio.timeout(TIMEOUT.total):
                ws = await self._session.ws_connect(f"ws://{self.host}/ws", heartbeat=30)
        except (TimeoutError, aiohttp.ClientError) as err:
            raise CannotConnect(str(err)) from err
        return RobotSocket(ws)

    async def unlock(self, pin: str) -> str:
        """Unlock with the Settings PIN; keeps and returns the session token."""
        status, body = await self._request("POST", "/api/auth/unlock", {"pin": pin})
        error = body.get("error") if isinstance(body, dict) else None
        if status == 200 and isinstance(body, dict) and "token" in body:
            self.token = str(body["token"])
            return self.token
        if error == "wrong_pin":
            raise WrongPin
        if error == "locked_out":
            raise LockedOut(int(body.get("retryAfter") or 0))
        raise CannotConnect(f"unlock answered {status}")

    async def _command(
        self,
        method: str,
        path: str,
        json: Any = None,
        data: Callable[[], Any] | None = None,
        timeout: aiohttp.ClientTimeout = TIMEOUT,
    ) -> tuple[int, Any]:
        """Send a command; on 401 pin_required, unlock with the PIN and retry once.

        Raises `PinRequired` when no PIN is stored, `WrongPin` / `LockedOut`
        when unlocking fails, and `Refused` for any other 4xx error code.
        """
        status, body = await self._request(method, path, json, data, timeout)
        if status == 401 and _error_code(body) == "pin_required":
            if not self.pin:
                raise PinRequired
            self.token = None
            await self.unlock(self.pin)
            status, body = await self._request(method, path, json, data, timeout)
        if 200 <= status < 300:
            return status, body
        code = _error_code(body)
        if code and 400 <= status < 500:
            raise Refused(code)
        raise CannotConnect(f"{method} {path} answered {status}")

    async def play(self, action: str) -> None:
        """Start (for the Session duration) or stop a Play session."""
        await self._command("POST", "/api/play", {"action": action})

    async def stow(self) -> None:
        """Stow the wand."""
        await self._command("POST", "/api/stow")

    async def position(self, axis: str, degrees: float) -> None:
        """Move one Axis to a position (Manual control)."""
        await self._command("POST", "/api/position", {"axis": axis, "degrees": degrees})

    async def update_settings(self, changes: dict[str, Any]) -> RobotSettings:
        """Change some settings (PUT /api/settings); returns them all."""
        _, body = await self._command("PUT", "/api/settings", changes)
        if not isinstance(body, dict):
            raise CannotConnect("PUT /api/settings answered no settings")
        return self._parse_settings(body)


    async def update_firmware(
        self, image: bytes, progress: Callable[[int, int], None]
    ) -> None:
        """Install a firmware image (POST /api/update); the robot then restarts.

        With a Settings PIN on, unlocks first so the image is only sent once.
        `progress` gets (bytes sent, total) as the upload goes.
        """
        auth = await self.auth()
        if auth.enabled and not auth.authorized:
            if not self.pin:
                raise PinRequired
            self.token = None
            await self.unlock(self.pin)

        def form() -> aiohttp.MultipartWriter:
            writer = aiohttp.MultipartWriter("form-data")
            part = writer.append_payload(_ImagePayload(image, progress))
            part.set_content_disposition("form-data", name="firmware", filename="firmware.bin")
            return writer

        await self._command("POST", "/api/update", data=form, timeout=UPDATE_TIMEOUT)


def _error_code(body: Any) -> str | None:
    code = body.get("error") if isinstance(body, dict) else None
    return code if isinstance(code, str) else None
