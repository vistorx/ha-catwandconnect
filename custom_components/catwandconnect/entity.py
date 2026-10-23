"""Base entity of a robot's live state."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import TypeVar

from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity, EntityDescription
from homeassistant.util import slugify

from .api import LockedOut, PinRequired, Refused, RobotError, WrongPin
from .const import DOMAIN
from .live import RobotLive

_T = TypeVar("_T")

# English entity names (translations/en.json), for the entity ids: the
# dashboards and automations in the docs use the English ids, whatever
# Home Assistant's language. tests/test_entity_ids.py keeps them in step.
ENGLISH_NAMES = {
    "activity": "Activity",
    "stow": "Stow",
    "play_session": "Play session",
    "session_duration": "Session duration",
    "horizontal_position": "Horizontal position",
    "vertical_position": "Vertical position",
    "horizontal_max_speed": "Horizontal maximum speed",
    "vertical_max_speed": "Vertical maximum speed",
    "firmware": "Firmware",
    "play_session_end": "Play session end",
    "sessions_today": "Sessions today",
}


class CatWandConnectEntity(Entity):
    """An entity fed by the robot's /ws state; unavailable while it is down."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _platform_domain: str

    def __init__(self, live: RobotLive, description: EntityDescription) -> None:
        self.live = live
        self.entity_description = description
        # Requested id for a new entity only; an existing one keeps its id.
        self.entity_id = (
            f"{self._platform_domain}."
            f"{slugify(f'{live.entry.title} {ENGLISH_NAMES[description.key]}')}"
        )
        self._attr_unique_id = f"{live.device_id}_{description.key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, live.device_id)})

    @property
    def available(self) -> bool:
        """Available while the robot's socket is up."""
        return self.live.connected

    async def async_added_to_hass(self) -> None:
        """Follow the robot's state."""
        self.async_on_remove(self.live.async_add_listener(self.async_write_ha_state))

    async def _command(self, command: Awaitable[_T]) -> _T:
        """Send a command to the robot, turning its errors into HA errors.

        The new state isn't guessed: the robot pushes it on /ws.
        """
        try:
            return await command
        except (WrongPin, PinRequired) as err:
            # Only setup and coordinators start reauth by themselves.
            self.live.entry.async_start_reauth(self.hass)
            raise command_error(err) from err
        except RobotError as err:
            raise command_error(err) from err


def command_error(err: RobotError) -> HomeAssistantError:
    """The Home Assistant error shown for a command the robot didn't take."""
    if isinstance(err, (WrongPin, PinRequired)):
        # The stored PIN no longer unlocks the robot: reauthentication.
        return ConfigEntryAuthFailed(
            translation_domain=DOMAIN, translation_key="wrong_pin"
        )
    if isinstance(err, LockedOut):
        return HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="locked_out",
            translation_placeholders={"retry_after": str(err.retry_after)},
        )
    if isinstance(err, Refused):
        return HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="command_refused",
            translation_placeholders={"error": err.code},
        )
    return HomeAssistantError(translation_domain=DOMAIN, translation_key="command_failed")
