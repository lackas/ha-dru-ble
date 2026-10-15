"""Tests for the config flow."""

from __future__ import annotations

from unittest.mock import patch

from bleak.exc import BleakError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dru_fireplace.const import DOMAIN
from homeassistant import config_entries
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from . import MAC, NAME, FakeFireplace, make_establish_connection, make_service_info


@pytest.fixture(autouse=True)
def mock_discovered() -> None:
    """Let the user step find the fireplace."""
    with patch(
        "custom_components.dru_fireplace.config_flow.async_discovered_service_info",
        return_value=[
            make_service_info(),
            make_service_info("Other", "AA:BB:CC:DD:EE:FF", fireplace=False),
        ],
    ):
        yield


@pytest.fixture(autouse=True)
def no_pairing_window() -> None:
    """Do not retry for a minute in tests."""
    with patch("custom_components.dru_fireplace.config_flow.PAIRING_WINDOW", 0):
        yield


async def finish_pairing(hass: HomeAssistant, result: dict) -> dict:
    """Submit the pair step and wait for the connection attempt."""
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    if result["type"] is FlowResultType.SHOW_PROGRESS:
        # The fake connects instantly, so the progress step usually completes
        # before the flow manager returns; cover the slow path as well.
        await hass.async_block_till_done()
        result = await hass.config_entries.flow.async_configure(result["flow_id"])
    await hass.async_block_till_done()
    return result


@pytest.mark.usefixtures("mock_ble_device")
async def test_user_flow(
    hass: HomeAssistant, mock_establish_connection: FakeFireplace
) -> None:
    """The user picks the fireplace, pairs and gets an entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ADDRESS: MAC}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "pair"

    result = await finish_pairing(hass, result)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == NAME
    assert result["data"] == {CONF_ADDRESS: MAC}
    assert result["result"].unique_id == MAC.lower()
    # Once for the pairing check, once for the setup of the entry.
    assert mock_establish_connection.connect_count == 2
    assert mock_establish_connection.is_connected


async def test_user_flow_no_devices(hass: HomeAssistant) -> None:
    """Without a fireplace in range the flow aborts."""
    with patch(
        "custom_components.dru_fireplace.config_flow.async_discovered_service_info",
        return_value=[],
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_devices_found"


async def test_user_flow_already_configured(hass: HomeAssistant) -> None:
    """A configured fireplace is not offered again."""
    MockConfigEntry(
        domain=DOMAIN, data={CONF_ADDRESS: MAC}, unique_id=MAC.lower()
    ).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_devices_found"


@pytest.mark.usefixtures("mock_establish_connection", "mock_ble_device")
async def test_bluetooth_flow(hass: HomeAssistant) -> None:
    """A discovered fireplace is confirmed, paired and added."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_BLUETOOTH},
        data=make_service_info(),
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "bluetooth_confirm"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "pair"

    result = await finish_pairing(hass, result)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_ADDRESS: MAC}


async def test_bluetooth_flow_already_configured(hass: HomeAssistant) -> None:
    """Discovery of a configured fireplace aborts."""
    MockConfigEntry(
        domain=DOMAIN, data={CONF_ADDRESS: MAC}, unique_id=MAC.lower()
    ).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_BLUETOOTH},
        data=make_service_info(),
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


@pytest.mark.usefixtures("mock_ble_device")
async def test_pairing_fails_then_succeeds(
    hass: HomeAssistant, fireplace: FakeFireplace
) -> None:
    """A failed pairing shows an error and the retry creates the entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ADDRESS: MAC}
    )
    with patch(
        "custom_components.dru_fireplace.client.establish_connection",
        side_effect=BleakError("Pairing failed due to error: 5"),
    ):
        result = await finish_pairing(hass, result)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "pair"
    assert result["errors"] == {"base": "cannot_connect"}

    fireplace.auth_ok = False
    with patch(
        "custom_components.dru_fireplace.client.establish_connection",
        side_effect=make_establish_connection(fireplace),
    ):
        result = await finish_pairing(hass, result)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "auth_failed"}

    fireplace.auth_ok = True
    with patch(
        "custom_components.dru_fireplace.client.establish_connection",
        side_effect=make_establish_connection(fireplace),
    ):
        result = await finish_pairing(hass, result)
    assert result["type"] is FlowResultType.CREATE_ENTRY
