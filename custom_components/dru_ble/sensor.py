"""Sensor entities for the DRU Fireplace Bluetooth integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from .coordinator import DruFireplaceConfigEntry, DruFireplaceCoordinator
from .entity import DruFireplaceEntity
from .protocol import FireplaceStatus, OperatingState

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class DruSensorEntityDescription(SensorEntityDescription):
    """Describe a fireplace sensor."""

    value_fn: Callable[[FireplaceStatus], StateType]


SENSORS: tuple[DruSensorEntityDescription, ...] = (
    DruSensorEntityDescription(
        key="room_temperature",
        translation_key="room_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        value_fn=lambda status: status.room_temperature,
    ),
    DruSensorEntityDescription(
        key="operating_state",
        translation_key="operating_state",
        device_class=SensorDeviceClass.ENUM,
        options=[state.value for state in OperatingState],
        value_fn=lambda status: status.operating_state,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DruFireplaceConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensor entities."""
    async_add_entities(
        DruFireplaceSensor(entry.runtime_data, description) for description in SENSORS
    )


class DruFireplaceSensor(DruFireplaceEntity, SensorEntity):
    """A sensor of the fireplace."""

    entity_description: DruSensorEntityDescription

    def __init__(
        self,
        coordinator: DruFireplaceCoordinator,
        description: DruSensorEntityDescription,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> StateType:
        """Return the value."""
        return self.entity_description.value_fn(self.status)
