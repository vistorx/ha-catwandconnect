"""Discovery from the robot's real mDNS answer, through Home Assistant's zeroconf.

vistorx/CatWandConnect#175: the robot did not show under *Discovered* on the
owner's Home Assistant. These tests start from the exact bytes a robot on
firmware 0.2.0-beta.2 sends back to a `_catwandconnect._tcp` PTR query
(captured on the owner's network, address rewritten to a documentation one),
and run them through the code Home Assistant itself uses: the zeroconf cache,
`info_from_service`, the manifest matchers and the discovery flow. They pin
that the firmware's records and the integration agree, so a missing
*Discovered* card points at the network, not at either side's code.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
from homeassistant import config_entries
from homeassistant.components.zeroconf.discovery import (
    ZeroconfDiscovery,
    info_from_service,
)
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from homeassistant.loader import async_get_zeroconf
from pytest_homeassistant_custom_component.common import MockConfigEntry
from zeroconf import DNSCache, DNSIncoming
from zeroconf.asyncio import AsyncServiceInfo

from custom_components.catwandconnect.const import CONF_PIN, DOMAIN

SERVICE_TYPE = "_catwandconnect._tcp.local."
SERVICE_NAME = f"catwandconnect.{SERVICE_TYPE}"
ROBOT_ID = "36d48570"
ROBOT_IP = "192.0.2.62"

# The robot's answer to a unicast PTR query for _catwandconnect._tcp.local.:
# PTR, SRV (port 80, catwandconnect.local.), TXT (name, version, api, id) and
# the A record, as ESP-IDF mdns on Arduino-ESP32 2.0.17 writes them. Only the
# last 4 bytes (the A record's address) were changed, to 192.0.2.62.
ROBOT_ANSWER = bytes.fromhex(
    "0000840000000003000000010f5f63617477616e64636f6e6e656374045f746370056c6f63"
    "616c00000c000100001194002b0e63617477616e64636f6e6e6563740f5f63617477616e64"
    "636f6e6e656374045f746370056c6f63616c000e63617477616e64636f6e6e656374c00c00"
    "2100010000007800170000000000500e63617477616e64636f6e6e656374c0210e636174"
    "77616e64636f6e6e656374c00c0010000100001194003b136e616d653d43617457616e6443"
    "6f6e6e6563741476657273696f6e3d302e322e302d626574612e32056170693d310b69643d"
    "3336643438353730c07e00010001000000780004c000023e"
)


def _robot_service() -> AsyncServiceInfo:
    """The service as Home Assistant's browser holds it after the answer."""
    cache = DNSCache()
    cache.async_add_records(DNSIncoming(ROBOT_ANSWER).answers())
    service = AsyncServiceInfo(SERVICE_TYPE, SERVICE_NAME)
    assert service.load_from_cache(SimpleNamespace(cache=cache))
    return service


def _robot_info() -> ZeroconfServiceInfo:
    info = info_from_service(_robot_service())
    assert info is not None
    return info


def test_robot_answer_decodes_like_home_assistant_sees_it() -> None:
    info = _robot_info()
    assert info.type == SERVICE_TYPE
    assert info.name == SERVICE_NAME
    assert info.hostname == "catwandconnect.local."
    assert info.port == 80
    assert str(info.ip_address) == ROBOT_IP
    # str keys and values, not bytes: what async_step_zeroconf reads.
    assert info.properties == {
        "name": "CatWandConnect",
        "version": "0.2.0-beta.2",
        "api": "1",
        "id": ROBOT_ID,
    }


async def test_manifest_registers_the_robots_service_type(hass: HomeAssistant) -> None:
    matchers = await async_get_zeroconf(hass)
    assert {"domain": DOMAIN} in matchers[SERVICE_TYPE]


async def test_robot_answer_starts_a_discovery_flow(hass: HomeAssistant) -> None:
    """Home Assistant's zeroconf turns the robot's answer into a *Discovered* card."""
    no_local_instance = AsyncServiceInfo(
        "_home-assistant._tcp.local.", "x._home-assistant._tcp.local."
    )
    discovery = ZeroconfDiscovery(
        hass, None, await async_get_zeroconf(hass), {}, {}, no_local_instance
    )
    discovery._async_process_service_update(_robot_service(), SERVICE_TYPE, SERVICE_NAME)
    await hass.async_block_till_done(wait_background_tasks=True)

    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert len(flows) == 1
    flow = flows[0]
    assert flow["context"]["source"] == config_entries.SOURCE_ZEROCONF
    assert flow["context"]["unique_id"] == ROBOT_ID
    assert flow["context"]["title_placeholders"] == {"name": "CatWandConnect"}
    assert flow["step_id"] == "zeroconf_confirm"


async def test_robot_added_by_ip_is_not_rediscovered(hass: HomeAssistant) -> None:
    """Once added by hand, the card stays away and the address follows the robot.

    This is the owner's state after #175: the entry came from the user step, so
    discovery aborts quietly as already configured instead of showing a card.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=ROBOT_ID,
        source=config_entries.SOURCE_USER,
        data={CONF_HOST: "192.0.2.10", CONF_PIN: ""},
        title="CatWandConnect",
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=_robot_info()
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == ROBOT_IP
    assert not hass.config_entries.flow.async_progress_by_handler(DOMAIN)


async def test_each_announcement_is_logged_for_debugging(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """With debug logging on, the owner sees that Home Assistant heard the robot."""
    caplog.set_level(logging.DEBUG, logger="custom_components.catwandconnect")
    await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=_robot_info()
    )
    assert (
        f"Robot {ROBOT_ID} announced at {ROBOT_IP} (api 1, firmware 0.2.0-beta.2)"
        in caplog.text
    )
