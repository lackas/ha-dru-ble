"""Fixtures for the DRU Fireplace tests."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dru_ble.const import DOMAIN
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import format_mac

from . import (
    MAC,
    NAME,
    STATUS_BURNING,
    FakeFireplace,
    make_ble_device,
    make_establish_connection,
)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable loading custom integrations."""


@pytest.fixture(autouse=True)
def mock_bluetooth(enable_bluetooth: None) -> None:
    """Enable the bluetooth integration."""


@pytest.fixture
def status() -> bytes:
    """Return the initial status of the fake fireplace."""
    return STATUS_BURNING


@pytest.fixture
def fireplace(status: bytes) -> FakeFireplace:
    """Return the fake fireplace."""
    return FakeFireplace(status)


@pytest.fixture
def mock_establish_connection(fireplace: FakeFireplace) -> Generator[FakeFireplace]:
    """Hand the fake fireplace to the client."""
    with patch(
        "custom_components.dru_ble.client.establish_connection",
        side_effect=make_establish_connection(fireplace),
    ):
        yield fireplace


@pytest.fixture
def mock_ble_device() -> Generator[None]:
    """Let the coordinator find the fireplace."""
    with patch(
        "custom_components.dru_ble.coordinator.bluetooth.async_ble_device_from_address",
        return_value=make_ble_device(),
    ):
        yield


@pytest.fixture
def config_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Return a config entry of the fireplace."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=NAME,
        data={CONF_ADDRESS: MAC},
        unique_id=format_mac(MAC),
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
async def setup_entry(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_establish_connection: FakeFireplace,
    mock_ble_device: None,
) -> MockConfigEntry:
    """Set up the integration with the fake fireplace."""
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry
