"""Async client for a CatWandConnect robot's Device API.

The only module that knows the robot's URLs and JSON shapes
(https://vistorx.github.io/CatWandConnect/api/).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import aiohttp

TIMEOUT = aiohttp.ClientTimeout(total=10)


class RobotError(Exception):
    """Base error talking to a robot."""


class CannotConnect(RobotError):
    """The robot can't be reached or answered something unexpected."""


class WrongPin(RobotError):
    """The Settings PIN was refused."""


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


@dataclass(frozen=True)
class AuthState:
    """What GET /api/auth says about the Settings PIN."""

    enabled: bool
    authorized: bool
    locked_for: int


class CatWandConnectClient:
    """Talks to one robot over HTTP."""

    def __init__(self, session: aiohttp.ClientSession, host: str) -> None:
        self._session = session
        self.host = host
        self.token: str | None = None

    @property
    def url(self) -> str:
        """Base URL of the robot's Device interface."""
        return f"http://{self.host}"

    async def _request(
        self, method: str, path: str, json: Any = None
    ) -> tuple[int, Any]:
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else None
        try:
            async with self._session.request(
                method, f"{self.url}{path}", json=json, headers=headers, timeout=TIMEOUT
            ) as resp:
                try:
                    body = await resp.json(content_type=None)
                except ValueError:
                    body = None
                return resp.status, body
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise CannotConnect(str(err)) from err

    async def _get_object(self, path: str) -> dict[str, Any]:
        status, body = await self._request("GET", path)
        if status != 200 or not isinstance(body, dict):
            raise CannotConnect(f"GET {path} answered {status}")
        return body

    async def info(self) -> RobotInfo:
        """Read the robot's identity and API version."""
        body = await self._get_object("/api/info")
        api = body.get("api")
        return RobotInfo(
            name=str(body.get("name") or "CatWandConnect"),
            version=str(body.get("version", "")),
            chip=body.get("chip"),
            api=api if isinstance(api, int) and not isinstance(api, bool) else None,
            device_id=body.get("id"),
        )

    async def auth(self) -> AuthState:
        """Read whether the Settings PIN is on."""
        body = await self._get_object("/api/auth")
        return AuthState(
            enabled=bool(body.get("enabled")),
            authorized=bool(body.get("authorized")),
            locked_for=int(body.get("lockedFor") or 0),
        )

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
