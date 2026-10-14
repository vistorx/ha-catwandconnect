"""The fake robot follows the documented Device API.

The integration's tests trust this fake, so it is checked against the contract
in https://vistorx.github.io/CatWandConnect/api/ here.
"""

from __future__ import annotations

import aiohttp
import pytest

from .fake_robot import FakeRobot


@pytest.fixture
async def session():
    async with aiohttp.ClientSession() as s:
        yield s


async def test_info_reports_identity_and_api_version(robot: FakeRobot, session) -> None:
    async with session.get(f"{robot.url}/api/info") as resp:
        assert resp.status == 200
        info = await resp.json()
    assert info == {
        "name": "CatWandConnect",
        "hostname": "catwandconnect.local",
        "version": "0.2.0",
        "chip": "ESP32-D0WD-V3",
        "api": 1,
        "id": "3f9a1c2b7d4e6f80",
    }


@pytest.mark.parametrize("robot_config", [{"api": None, "version": "0.1.0"}])
async def test_old_firmware_has_no_api_version(robot: FakeRobot, session) -> None:
    async with session.get(f"{robot.url}/api/info") as resp:
        info = await resp.json()
    assert "api" not in info
    assert "id" not in info
    assert info["version"] == "0.1.0"


async def test_auth_without_pin(robot: FakeRobot, session) -> None:
    async with session.get(f"{robot.url}/api/auth") as resp:
        assert await resp.json() == {"enabled": False, "authorized": False, "lockedFor": 0}


@pytest.mark.parametrize("robot_config", [{"pin": "2468"}])
async def test_unlock_with_right_pin_authorizes(robot: FakeRobot, session) -> None:
    async with session.post(f"{robot.url}/api/auth/unlock", json={"pin": "2468"}) as resp:
        assert resp.status == 200
        token = (await resp.json())["token"]
    headers = {"Authorization": f"Bearer {token}"}
    async with session.get(f"{robot.url}/api/auth", headers=headers) as resp:
        assert await resp.json() == {"enabled": True, "authorized": True, "lockedFor": 0}


@pytest.mark.parametrize("robot_config", [{"pin": "2468"}])
async def test_wrong_pin_then_locked_out(robot: FakeRobot, session) -> None:
    for _ in range(5):
        async with session.post(f"{robot.url}/api/auth/unlock", json={"pin": "0000"}) as resp:
            assert resp.status == 401
            assert await resp.json() == {"error": "wrong_pin"}
    async with session.post(f"{robot.url}/api/auth/unlock", json={"pin": "2468"}) as resp:
        assert resp.status == 429
        assert await resp.json() == {"error": "locked_out", "retryAfter": 30}


@pytest.mark.parametrize("robot_config", [{"pin": "2468"}])
async def test_settings_need_pin_except_play_fields(robot: FakeRobot, session) -> None:
    body = {"axes": {"horizontal": {"maxSpeed": 120}}}
    async with session.put(f"{robot.url}/api/settings", json=body) as resp:
        assert resp.status == 401
        assert await resp.json() == {"error": "pin_required"}
    async with session.put(f"{robot.url}/api/settings", json={"sessionMinutes": 15}) as resp:
        assert resp.status == 200
    async with session.post(f"{robot.url}/api/auth/unlock", json={"pin": "2468"}) as resp:
        token = (await resp.json())["token"]
    headers = {"Authorization": f"Bearer {token}"}
    async with session.put(f"{robot.url}/api/settings", json=body, headers=headers) as resp:
        assert resp.status == 200
    async with session.get(f"{robot.url}/api/settings") as resp:
        settings = await resp.json()
    assert settings["sessionMinutes"] == 15
    assert settings["axes"]["horizontal"]["maxSpeed"] == 120


async def test_play_start_and_stop(robot: FakeRobot, session) -> None:
    async with session.get(f"{robot.url}/api/play") as resp:
        assert await resp.json() == {"active": False, "remaining": 0, "minutes": 10}
    body = {"action": "start", "sessionMinutes": 20}
    async with session.post(f"{robot.url}/api/play", json=body) as resp:
        assert resp.status == 200
        assert await resp.json() == {"active": True, "remaining": 1200, "minutes": 20}
    async with session.post(f"{robot.url}/api/play", json={"action": "stop"}) as resp:
        assert await resp.json() == {"active": False, "remaining": 0, "minutes": 20}
    assert robot.activity == "stowing"


@pytest.mark.parametrize(
    ("robot_config", "status", "error"),
    [
        ({"calibrated": False}, 409, "not_calibrated"),
        ({"activity": "stowing"}, 409, "busy"),
        ({"activity": "calibrating"}, 409, "busy"),
    ],
)
async def test_play_start_refused(robot: FakeRobot, session, status, error) -> None:
    async with session.post(f"{robot.url}/api/play", json={"action": "start"}) as resp:
        assert resp.status == status
        assert await resp.json() == {"error": error}


async def test_play_rejects_bad_requests(robot: FakeRobot, session) -> None:
    body = {"action": "start", "sessionMinutes": 61}
    async with session.post(f"{robot.url}/api/play", json=body) as resp:
        assert resp.status == 400
        assert await resp.json() == {"error": "session_duration_out_of_range"}
    async with session.post(f"{robot.url}/api/play", json={"action": "dance"}) as resp:
        assert resp.status == 400
        assert await resp.json() == {"error": "invalid_request"}


async def test_stow_accepted(robot: FakeRobot, session) -> None:
    async with session.post(f"{robot.url}/api/stow") as resp:
        assert resp.status == 202
    assert robot.activity == "stowing"


async def test_position_clamped_into_travel_limits(robot: FakeRobot, session) -> None:
    body = {"axis": "horizontal", "degrees": 170}
    async with session.post(f"{robot.url}/api/position", json=body) as resp:
        assert resp.status == 200
    assert robot.h == 120
    assert robot.activity == "manual"
    async with session.post(f"{robot.url}/api/position", json={"axis": "up", "degrees": 1}) as resp:
        assert resp.status == 400


async def test_ws_pushes_state_on_connect_and_change(robot: FakeRobot, session) -> None:
    async with session.ws_connect(f"{robot.url}/ws") as ws:
        first = await ws.receive_json(timeout=2)
        assert first["t"] == "state"
        assert first["activity"] == "idle"
        assert "play" not in first

        await session.post(f"{robot.url}/api/play", json={"action": "start"})
        playing = await ws.receive_json(timeout=2)
        assert playing["activity"] == "playing"
        assert playing["play"] == {"remaining": 600}

        await robot.set_activity("manual")
        manual = await ws.receive_json(timeout=2)
        assert manual["activity"] == "manual"


async def test_disconnect_closes_ws(robot: FakeRobot, session) -> None:
    async with session.ws_connect(f"{robot.url}/ws") as ws:
        await ws.receive_json(timeout=2)
        assert robot.ws_clients == 1
        await robot.disconnect()
        msg = await ws.receive(timeout=2)
        assert msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED)
    assert robot.ws_clients == 0
