"""Diagnostics for the DRU Fireplace integration."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant

from .coordinator import DruFireplaceConfigEntry

TO_REDACT = {CONF_ADDRESS, "serial_number", "title"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: DruFireplaceConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    status = coordinator.data
    return async_redact_data(
        {
            "entry": {"title": entry.title, "data": dict(entry.data)},
            "identity": asdict(coordinator.client.identity),
            "connected": coordinator.client.is_connected,
            "status": None
            if status is None
            else {
                "raw": status.raw.hex(),
                "operating_state": status.operating_state,
                "flame": status.flame,
                "target_temperature": status.target_temperature,
                "room_temperature": status.room_temperature,
                "thermostat_mode": status.thermostat_mode,
                "eco": status.eco,
                "second_burner": status.second_burner,
                "adjusting": status.adjusting,
            },
        },
        TO_REDACT,
    )
