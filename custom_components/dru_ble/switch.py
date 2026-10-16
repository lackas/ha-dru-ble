"""Switch entities for the DRU Fireplace Bluetooth integration."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .client import DruFireplaceClient
from .coordinator import DruFireplaceConfigEntry, DruFireplaceCoordinator
from .entity import DruFireplaceEntity
from .protocol import FireplaceCapabilities, FireplaceStatus

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class DruSwitchEntityDescription(SwitchEntityDescription):
    """Describe a fireplace switch."""

    is_on_fn: Callable[[FireplaceStatus], bool]
    set_fn: Callable[[DruFireplaceClient, bool], Coroutine[Any, Any, None]]
    exists_fn: Callable[[FireplaceCapabilities | None], bool] = lambda _: True


SWITCHES: tuple[DruSwitchEntityDescription, ...] = (
    DruSwitchEntityDescription(
        key="eco",
        translation_key="eco",
        is_on_fn=lambda status: status.eco,
        set_fn=lambda client, enabled: client.async_set_eco(enabled),
    ),
    DruSwitchEntityDescription(
        key="second_burner",
        translation_key="second_burner",
        is_on_fn=lambda status: status.second_burner,
        set_fn=lambda client, enabled: client.async_set_second_burner(enabled),
        exists_fn=lambda capabilities: (
            capabilities is None or capabilities.second_burner
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DruFireplaceConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the switch entities."""
    coordinator = entry.runtime_data
    capabilities = coordinator.client.capabilities
    async_add_entities(
        DruFireplaceSwitch(coordinator, description)
        for description in SWITCHES
        if description.exists_fn(capabilities)
    )


class DruFireplaceSwitch(DruFireplaceEntity, SwitchEntity):
    """A switch of the fireplace."""

    entity_description: DruSwitchEntityDescription

    def __init__(
        self,
        coordinator: DruFireplaceCoordinator,
        description: DruSwitchEntityDescription,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool:
        """Return the state."""
        return self.entity_description.is_on_fn(self.status)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on."""
        await self._async_send(
            self.entity_description.set_fn(self.coordinator.client, True)
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off."""
        await self._async_send(
            self.entity_description.set_fn(self.coordinator.client, False)
        )
