"""Climate entity for the DRU Fireplace Bluetooth integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import (
    ATTR_TEMPERATURE,
    PRECISION_HALVES,
    PRECISION_TENTHS,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    MAX_TARGET_TEMPERATURE,
    MIN_TARGET_TEMPERATURE,
    PRESET_MANUAL,
    PRESET_THERMOSTAT,
)
from .coordinator import DruFireplaceConfigEntry
from .entity import DruFireplaceEntity
from .protocol import OperatingState

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DruFireplaceConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the climate entity."""
    async_add_entities([DruFireplaceClimate(entry.runtime_data)])


class DruFireplaceClimate(DruFireplaceEntity, ClimateEntity):
    """The fireplace as a heater.

    Off/heat switches the burner. The preset selects whether the flame is
    set by hand (manual) or follows the target temperature (thermostat).
    """

    _attr_name = None
    _attr_translation_key = "fireplace"
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_preset_modes = [PRESET_MANUAL, PRESET_THERMOSTAT]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_precision = PRECISION_TENTHS
    _attr_target_temperature_step = PRECISION_HALVES
    _attr_min_temp = MIN_TARGET_TEMPERATURE
    _attr_max_temp = MAX_TARGET_TEMPERATURE

    @property
    def hvac_mode(self) -> HVACMode:
        """Return off or heat."""
        return HVACMode.HEAT if self.status.is_on else HVACMode.OFF

    @property
    def hvac_action(self) -> HVACAction:
        """Return what the burner is doing."""
        status = self.status
        if status.operating_state is OperatingState.IGNITING:
            return HVACAction.PREHEATING
        if status.is_burning:
            return HVACAction.HEATING if status.flame else HVACAction.IDLE
        return HVACAction.OFF

    @property
    def preset_mode(self) -> str:
        """Return manual or thermostat."""
        return PRESET_THERMOSTAT if self.status.thermostat_mode else PRESET_MANUAL

    @property
    def current_temperature(self) -> float | None:
        """Return the room temperature measured by the remote control."""
        return self.status.room_temperature

    @property
    def target_temperature(self) -> float:
        """Return the target temperature."""
        return self.status.target_temperature

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Ignite or switch off the fireplace."""
        if hvac_mode is HVACMode.OFF:
            await self._async_send(self.coordinator.client.async_turn_off())
        else:
            await self._async_send(self.coordinator.client.async_turn_on())

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Switch between manual flame control and thermostat mode."""
        await self._async_send(
            self.coordinator.client.async_set_thermostat_mode(
                preset_mode == PRESET_THERMOSTAT
            )
        )

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the target temperature."""
        if (hvac_mode := kwargs.get(ATTR_HVAC_MODE)) is not None:
            await self.async_set_hvac_mode(hvac_mode)
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is not None:
            await self._async_send(
                self.coordinator.client.async_set_target_temperature(temperature)
            )
