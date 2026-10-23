"""Entity ids stay in English whatever Home Assistant's language.

The ready-made dashboards and the docs' automations use the English ids
(`switch.catwandconnect_play_session`), so a French Home Assistant must not
build them from the translated names (`switch.catwandconnect_session_de_jeu`).
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .common import (
    ACTIVITY,
    FIRMWARE,
    H_MAX_SPEED,
    H_POSITION,
    PLAY_SESSION,
    PLAY_SESSION_END,
    SESSION_DURATION,
    STOW,
    V_MAX_SPEED,
    V_POSITION,
    set_up,
)
from .fake_robot import FakeRobot

ALL = {
    ACTIVITY, FIRMWARE, H_MAX_SPEED, H_POSITION, PLAY_SESSION, PLAY_SESSION_END,
    SESSION_DURATION, STOW, V_MAX_SPEED, V_POSITION,
}


async def test_french_home_assistant_gets_english_ids(hass: HomeAssistant, robot: FakeRobot) -> None:
    await hass.config.async_update(language="fr")
    entry = await set_up(hass, robot)
    ids = {e.entity_id for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)}
    assert ids == ALL
    # The names are still translated.
    assert hass.states.get(PLAY_SESSION).attributes["friendly_name"] == "CatWandConnect Session de jeu"


async def test_ids_follow_the_robot_name(hass: HomeAssistant, robot: FakeRobot) -> None:
    robot.name = "CatWandConnect salon"
    from homeassistant.const import CONF_HOST
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.catwandconnect.const import CONF_PIN, DOMAIN

    entry = MockConfigEntry(domain=DOMAIN, unique_id=robot.device_id,
                            data={CONF_HOST: robot.host, CONF_PIN: ""}, title=robot.name)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    ids = {e.entity_id for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)}
    assert "switch.catwandconnect_salon_play_session" in ids
    assert "number.catwandconnect_salon_horizontal_maximum_speed" in ids


def test_english_names_match_the_translations() -> None:
    import json
    from pathlib import Path

    from custom_components.catwandconnect.entity import ENGLISH_NAMES

    en = json.loads((Path(__file__).parents[1] / "custom_components/catwandconnect/translations/en.json").read_text())
    names = {k: v["name"] for platform in en["entity"].values() for k, v in platform.items()}
    assert ENGLISH_NAMES == names
