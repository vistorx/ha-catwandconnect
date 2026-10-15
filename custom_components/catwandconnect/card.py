"""Serve the joystick card and make the dashboards load it.

The card is a single ES module in `frontend/`, served by Home Assistant's own
web server, so owners add it like any card without registering a resource by
hand. It is loaded two ways:

- as an extra module of the page (`add_extra_js_url`), which browsers pick up;
- as a dashboard resource (storage mode), which the companion apps need: they
  keep the page they loaded first and only fetch dashboard resources again, so
  without it the card shows "Configuration error" on a phone.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

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
    if "lovelace" in hass.config.components:
        await _async_ensure_resource(hass)


async def _async_ensure_resource(hass: HomeAssistant) -> None:
    """Keep exactly one dashboard resource for the card, at this version."""
    from homeassistant.components.lovelace.const import LOVELACE_DATA, MODE_STORAGE

    data = hass.data.get(LOVELACE_DATA)
    if data is None or data.resource_mode != MODE_STORAGE:
        # YAML resources belong to the owner: the guide says what to add.
        return
    resources = data.resources
    await resources.async_get_info()  # loads the stored resources
    url = f"{URL_BASE}/{CARD_FILE}?v={await hass.async_add_executor_job(_version)}"
    ours = [
        item
        for item in resources.async_items()
        if str(item.get("url", "")).split("?")[0] == f"{URL_BASE}/{CARD_FILE}"
    ]
    try:
        if not ours:
            await resources.async_create_item({"res_type": "module", "url": url})
            return
        first, *duplicates = ours
        if first["url"] != url:
            await resources.async_update_item(first["id"], {"res_type": "module", "url": url})
        for item in duplicates:
            await resources.async_delete_item(item["id"])
    except Exception:  # the card still works in browsers
        _LOGGER.warning(
            "Could not register the joystick card as a dashboard resource",
            exc_info=True,
        )
