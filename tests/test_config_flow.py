"""The placeholder config flow (the real one comes with vistorx/CatWandConnect#158)."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.catwandconnect.const import DOMAIN


async def test_user_step_shows_host_form_then_aborts(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "catwandconnect.local"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_implemented"
