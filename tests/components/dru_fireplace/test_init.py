"""Tests for setup, reconnect and diagnostics."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from bleak.exc import BleakError
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.dru_fireplace.diagnostics import (
    async_get_config_entry_diagnostics,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util

from . import MAC, FakeFireplace

CLIMATE = "climate.dfgt_00test00"


async def test_setup_creates_device(
    hass: HomeAssistant, setup_entry: MockConfigEntry, fireplace: FakeFireplace
) -> None:
    """Setup connects once and registers the device with its identity."""
    assert setup_entry.state is ConfigEntryState.LOADED
    assert fireplace.connect_count == 1
    device = dr.async_get(hass).async_get_device_by_connection(
        (dr.CONNECTION_BLUETOOTH, MAC.lower()), setup_entry.entry_id
    )
    assert device is not None
    assert device.manufacturer == "DRU"
    assert device.model == "MS75TALL TNNL cer"
    assert device.model_id == "P2025.002 V5"
    assert device.serial_number == "TEST0000000000000001"
    assert hass.states.get(CLIMATE).state == "heat"


async def test_setup_retries_without_device(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_establish_connection: FakeFireplace,
) -> None:
    """Setup retries while the fireplace is out of range."""
    with patch(
        "custom_components.dru_fireplace.coordinator.bluetooth.async_ble_device_from_address",
        return_value=None,
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_RETRY
    assert mock_establish_connection.connect_count == 0


async def test_setup_retries_on_connection_error(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_ble_device: None
) -> None:
    """Setup retries when connecting fails."""
    with patch(
        "custom_components.dru_fireplace.client.establish_connection",
        side_effect=BleakError("out of slots"),
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_reconnect_after_link_drop(
    hass: HomeAssistant, setup_entry: MockConfigEntry, fireplace: FakeFireplace
) -> None:
    """A dropped link makes the entities unavailable until the reconnect."""
    fireplace.drop_link()
    assert hass.states.get(CLIMATE).state == STATE_UNAVAILABLE

    await hass.async_block_till_done()
    assert fireplace.connect_count == 2
    assert hass.states.get(CLIMATE).state == "heat"


async def test_poll_reads_status(
    hass: HomeAssistant, setup_entry: MockConfigEntry, fireplace: FakeFireplace
) -> None:
    """The periodic poll reads the status without reconnecting."""
    fireplace.status[2] = 33
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()
    assert fireplace.connect_count == 1
    assert hass.states.get("number.dfgt_00test00_flame_height").state == "33"


async def test_unload(
    hass: HomeAssistant, setup_entry: MockConfigEntry, fireplace: FakeFireplace
) -> None:
    """Unloading disconnects."""
    assert await hass.config_entries.async_unload(setup_entry.entry_id)
    await hass.async_block_till_done()
    assert setup_entry.state is ConfigEntryState.NOT_LOADED
    assert not fireplace.is_connected


@pytest.mark.usefixtures("setup_entry")
async def test_diagnostics(hass: HomeAssistant, setup_entry: MockConfigEntry) -> None:
    """Diagnostics expose the identity and the decoded status."""
    diagnostics = await async_get_config_entry_diagnostics(hass, setup_entry)
    assert diagnostics["connected"] is True
    assert diagnostics["identity"]["serial_number"] == "TEST0000000000000001"
    assert diagnostics["status"]["operating_state"] == "burning"
    assert diagnostics["status"]["flame"] == 82
    assert diagnostics["status"]["raw"] == "03005200000000140000b84115aea94100"
