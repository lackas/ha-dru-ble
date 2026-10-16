"""Binary sensor entities for the DRU Fireplace Bluetooth integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import DruFireplaceConfigEntry, DruFireplaceCoordinator
from .entity import DruFireplaceEntity

PARALLEL_UPDATES = 0

LIGHT = BinarySensorEntityDescription(
    key="light",
    translation_key="light",
    device_class=BinarySensorDeviceClass.LIGHT,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DruFireplaceConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensor entities."""
    coordinator = entry.runtime_data
    capabilities = coordinator.client.capabilities
    if capabilities is None or capabilities.light:
        async_add_entities([DruFireplaceLightSensor(coordinator, LIGHT)])


class DruFireplaceLightSensor(DruFireplaceEntity, BinarySensorEntity):
    """The lamp output, switched by the lamp key of the remote control."""

    def __init__(
        self,
        coordinator: DruFireplaceCoordinator,
        description: BinarySensorEntityDescription,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool:
        """Return True while the lamp output is on."""
        return self.status.light
