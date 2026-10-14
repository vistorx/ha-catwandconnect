"""Serve the joystick card and make the dashboards load it.

The card is a single ES module in `frontend/`, served by Home Assistant's own
web server and added to every dashboard page, so owners add it like any card
without registering a resource by hand.
"""

from __future__ import annotations

import json
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import DOMAIN

CARD_FILE = "catwandconnect-joystick-card.js"
FRONTEND_DIR = Path(__file__).parent / "frontend"
URL_BASE = f"/{DOMAIN}/frontend"


def _version() -> str:
    manifest = json.loads((Path(__file__).parent / "manifest.json").read_text())
    return str(manifest["version"])


async def async_register_card(hass: HomeAssistant) -> None:
    """Serve the card's file and load it on every dashboard (once per start)."""
    await hass.http.async_register_static_paths(
        [StaticPathConfig(URL_BASE, str(FRONTEND_DIR), cache_headers=False)]
    )
    if "frontend" in hass.config.components:
        version = await hass.async_add_executor_job(_version)
        # The version busts the browser cache after an update.
        add_extra_js_url(hass, f"{URL_BASE}/{CARD_FILE}?v={version}")
