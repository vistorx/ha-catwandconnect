"""Play session switch: on while the robot plays on its own."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CatWandConnectConfigEntry
from .api import Refused, RobotError
from .const import DOMAIN
from .entity import CatWandConnectEntity, command_error

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

PLAY_SESSION = SwitchEntityDescription(key="play_session", translation_key="play_session")

# Why the robot refuses to start a Play session (409), and the message shown.
_REFUSALS = {"not_calibrated": "play_not_calibrated", "busy": "play_busy"}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CatWandConnectConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the Play session switch."""
    async_add_entities([PlaySessionSwitch(entry.runtime_data, PLAY_SESSION)])


class PlaySessionSwitch(CatWandConnectEntity, SwitchEntity):
    """Starts and stops a Play session; on while the activity is playing."""

    @property
    def is_on(self) -> bool | None:
        """On during a Play session."""
        state = self.live.state
        return state.activity == "playing" if state else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Start a Play session for the Session duration."""
        try:
            await self.live.client.play("start")
        except Refused as err:
            if err.code not in _REFUSALS:
                raise command_error(err) from err
            # The switch stays off: the robot pushes no change.
            _LOGGER.warning(
                "%s refused to start a Play session: %s",
                self.live.entry.title,
                err.code,
            )
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key=_REFUSALS[err.code]
            ) from err
        except RobotError as err:
            raise command_error(err) from err

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop the Play session; the robot Stows."""
        await self._command(self.live.client.play("stop"))
