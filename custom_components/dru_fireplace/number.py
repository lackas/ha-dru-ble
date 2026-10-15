"""Number entity for the DRU Fireplace integration."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import DruFireplaceConfigEntry
from .entity import DruFireplaceEntity
from .protocol import FLAME_MAX, FLAME_MIN

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DruFireplaceConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the flame height entity."""
    async_add_entities([DruFlameHeightNumber(entry.runtime_data)])


class DruFlameHeightNumber(DruFireplaceEntity, NumberEntity):
    """Flame height in percent.

    Setting a value while the thermostat controls the flame returns the
    fireplace to manual control, the same as pressing the remote.
    """

    _attr_translation_key = "flame_height"
    _attr_native_min_value = FLAME_MIN
    _attr_native_max_value = FLAME_MAX
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator) -> None:  # noqa: ANN001
        """Initialize the entity."""
        super().__init__(coordinator, "flame_height")

    @property
    def native_value(self) -> int | None:
        """Return the flame height, unknown while the fireplace is off."""
        return self.status.flame if self.status.is_burning else None

    async def async_set_native_value(self, value: float) -> None:
        """Set the flame height."""
        await self._async_send(self.coordinator.client.async_set_flame(int(value)))
