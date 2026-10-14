"""Constants for the CatWandConnect integration."""

from typing import Final

DOMAIN: Final = "catwandconnect"

CONF_PIN: Final = "pin"

MANUFACTURER: Final = "CatWandConnect"
MODEL: Final = "CatWandConnect"

# Lowest robot API version this integration speaks (docs/api.md, "API version").
MIN_API_VERSION: Final = 1
# First firmware with API version 1, shown to owners whose robot is too old.
MIN_FIRMWARE: Final = "0.2.0-beta.2"
UPDATE_URL: Final = (
    "https://vistorx.github.io/CatWandConnect/install/#updating-building-from-source"
)
