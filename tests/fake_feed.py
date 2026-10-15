"""A fake Update feed: the CatWandConnect flasher site on GitHub Pages.

Serves `channels.json` and the OTA images under one base URL, like
https://vistorx.github.io/CatWandConnect/flasher/. The default feed has the
shape live before the firmware's extended feed: only `version` and `tag` per
channel, so no update can be installed from it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from aiohttp import web
from aiohttp.test_utils import TestServer

# An ESP app image starts with the magic byte 0xE9; the rest is filler, big
# enough to be uploaded in several chunks.
IMAGE = b"\xe9" + bytes(range(256)) * 800


def old_feed() -> dict[str, Any]:
    """The feed as served before the firmware's extended feed."""
    return {
        "stable": {"version": "0.1.0", "tag": "v0.1.0"},
        "beta": {"version": "0.2.0-beta.3", "tag": "v0.2.0-beta.3"},
    }


def channel(version: str, summary: str = "") -> dict[str, Any]:
    """One channel of the extended feed, with its three OTA images."""
    name = "beta" if "-" in version else "stable"
    return {
        "version": version,
        "tag": f"v{version}",
        "notes": f"https://github.com/vistorx/CatWandConnect/releases/tag/v{version}",
        "summary": summary,
        "ota": {
            "ESP32": f"{name}/catwandconnect-esp32-ota.bin",
            "ESP32-S3": f"{name}/catwandconnect-esp32s3-ota.bin",
            "ESP32-C3": f"{name}/catwandconnect-esp32c3-ota.bin",
        },
    }


@dataclass
class FakeFeed:
    """The flasher site: `channels.json` plus files, both changeable per test."""

    channels: Any = field(default_factory=old_feed)
    files: dict[str, bytes] = field(default_factory=dict)
    # Answer every request with this status instead (e.g. 500).
    status: int | None = None
    requests: list[str] = field(default_factory=list)
    _server: TestServer | None = None

    def app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/flasher/{path:.*}", self._get)
        return app

    async def start(self) -> None:
        self._server = TestServer(self.app(), host="127.0.0.1")
        await self._server.start_server()

    async def close(self) -> None:
        if self._server is not None:
            await self._server.close()
            self._server = None

    @property
    def url(self) -> str:
        """Base URL, ending with a slash like the real one."""
        assert self._server is not None, "feed not started"
        return f"http://127.0.0.1:{self._server.port}/flasher/"

    def publish(self, **channels: dict[str, Any]) -> None:
        """Serve these channels, each with an image for every chip family."""
        self.channels = channels
        for entry in channels.values():
            for path in entry.get("ota", {}).values():
                self.files.setdefault(path, IMAGE)

    async def _get(self, request: web.Request) -> web.StreamResponse:
        path = request.match_info["path"]
        self.requests.append(path)
        if self.status is not None:
            return web.Response(status=self.status)
        if path == "channels.json":
            return web.json_response(self.channels)
        if path in self.files:
            return web.Response(body=self.files[path], content_type="application/octet-stream")
        return web.Response(status=404)
