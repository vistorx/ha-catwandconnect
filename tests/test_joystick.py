"""Joystick card: its websocket commands and the JavaScript file HA serves."""

from __future__ import annotations

from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL, UrlManager
from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.setup import async_setup_component

from custom_components.catwandconnect.api import CannotConnect
from custom_components.catwandconnect.const import DOMAIN

from .common import ACTIVITY, set_up, state_of, until
from .fake_robot import FakeRobot

CARD_URL = "/catwandconnect/frontend/catwandconnect-joystick-card.js"


def _device_id(hass: HomeAssistant, robot: FakeRobot) -> str:
    (entry,) = hass.config_entries.async_entries(DOMAIN)
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, robot.device_id), entry.entry_id
    )
    assert device is not None
    return device.id


async def test_move_forwards_clamped_deflections(
    hass: HomeAssistant, robot: FakeRobot, hass_ws_client
) -> None:
    await set_up(hass, robot)
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {
            "type": "catwandconnect/move",
            "device_id": _device_id(hass, robot),
            "h": 0.5,
            "v": -3,
        }
    )
    msg = await client.receive_json()

    assert msg["success"], msg
    await until(lambda: {"t": "move", "h": 0.5, "v": -1.0} in robot.ws_frames)
    await until(lambda: state_of(hass, ACTIVITY) == "manual")


async def test_move_accepts_the_config_entry_id(
    hass: HomeAssistant, robot: FakeRobot, hass_ws_client
) -> None:
    entry = await set_up(hass, robot)
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {"type": "catwandconnect/move", "entry_id": entry.entry_id, "h": 2, "v": 0}
    )
    msg = await client.receive_json()

    assert msg["success"], msg
    await until(lambda: {"t": "move", "h": 1.0, "v": 0.0} in robot.ws_frames)


async def test_stop_forwards_stop(
    hass: HomeAssistant, robot: FakeRobot, hass_ws_client
) -> None:
    await set_up(hass, robot)
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {"type": "catwandconnect/stop", "device_id": _device_id(hass, robot)}
    )
    msg = await client.receive_json()

    assert msg["success"], msg
    await until(lambda: {"t": "stop"} in robot.ws_frames)


async def test_unknown_device_is_an_error(
    hass: HomeAssistant, robot: FakeRobot, hass_ws_client
) -> None:
    await set_up(hass, robot)
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {"type": "catwandconnect/move", "device_id": "nope", "h": 0, "v": 0}
    )
    msg = await client.receive_json()

    assert not msg["success"]
    assert msg["error"]["code"] == "not_found"
    assert [f for f in robot.ws_frames if f.get("t") != "hello"] == []


async def test_offline_robot_is_an_error(
    hass: HomeAssistant, robot: FakeRobot, hass_ws_client
) -> None:
    await set_up(hass, robot)
    device_id = _device_id(hass, robot)
    await robot.go_offline()
    await until(lambda: state_of(hass, ACTIVITY) == "unavailable")
    client = await hass_ws_client(hass)

    await client.send_json_auto_id({"type": "catwandconnect/stop", "device_id": device_id})
    msg = await client.receive_json()

    assert not msg["success"]
    assert msg["error"]["code"] == "not_connected"


async def test_send_failure_is_an_error(
    hass: HomeAssistant, robot: FakeRobot, hass_ws_client, monkeypatch
) -> None:
    entry = await set_up(hass, robot)

    async def broken(frame):
        raise CannotConnect("socket closing")

    monkeypatch.setattr(entry.runtime_data._socket, "send", broken)
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {"type": "catwandconnect/move", "entry_id": entry.entry_id, "h": 0, "v": 1}
    )
    msg = await client.receive_json()

    assert not msg["success"]
    assert msg["error"]["code"] == "not_connected"


async def test_move_needs_numbers(
    hass: HomeAssistant, robot: FakeRobot, hass_ws_client
) -> None:
    await set_up(hass, robot)
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {
            "type": "catwandconnect/move",
            "device_id": _device_id(hass, robot),
            "h": "left",
            "v": 0,
        }
    )
    msg = await client.receive_json()

    assert not msg["success"]
    assert msg["error"]["code"] == "invalid_format"
    assert [f for f in robot.ws_frames if f.get("t") != "hello"] == []


async def test_move_needs_a_robot(
    hass: HomeAssistant, robot: FakeRobot, hass_ws_client
) -> None:
    await set_up(hass, robot)
    client = await hass_ws_client(hass)

    await client.send_json_auto_id({"type": "catwandconnect/move", "h": 0, "v": 0})
    msg = await client.receive_json()

    assert not msg["success"]
    assert msg["error"]["code"] == "invalid_format"


async def test_card_is_served(hass: HomeAssistant, hass_client) -> None:
    assert await async_setup_component(hass, "http", {})
    assert await async_setup_component(hass, DOMAIN, {})
    client = await hass_client()

    resp = await client.get(CARD_URL)

    assert resp.status == 200
    assert "customElements.define" in await resp.text()


async def test_card_is_loaded_by_the_frontend(hass: HomeAssistant) -> None:
    urls = UrlManager(lambda *_: None, [])
    hass.data[DATA_EXTRA_MODULE_URL] = urls
    hass.config.components.add("frontend")

    assert await async_setup_component(hass, DOMAIN, {})

    assert any(url.startswith(f"{CARD_URL}?v=") for url in urls.urls)


async def test_card_is_a_dashboard_resource(hass: HomeAssistant) -> None:
    """The companion apps keep an old page: a resource loads on every dashboard."""
    assert await async_setup_component(hass, "lovelace", {})
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    resources = hass.data[LOVELACE_DATA].resources
    await resources.async_get_info()
    urls = [item["url"] for item in resources.async_items()]
    assert len([u for u in urls if u.startswith(f"{CARD_URL}?v=")]) == 1
    (item,) = [i for i in resources.async_items() if i["url"].startswith(CARD_URL)]
    assert item["type"] == "module"


async def test_card_resource_follows_the_version(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, "lovelace", {})
    resources = hass.data[LOVELACE_DATA].resources
    await resources.async_get_info()
    await resources.async_create_item({"res_type": "module", "url": f"{CARD_URL}?v=0.0.1"})
    await resources.async_create_item({"res_type": "module", "url": "/local/other.js"})

    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    urls = sorted(item["url"] for item in resources.async_items())
    assert "/local/other.js" in urls
    card = [u for u in urls if u.startswith(CARD_URL)]
    assert len(card) == 1 and not card[0].endswith("v=0.0.1")
