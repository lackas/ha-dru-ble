"""Base entity for the DRU Fireplace integration."""

from __future__ import annotations

from collections.abc import Coroutine
from typing import Any

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.device_registry import (
    CONNECTION_BLUETOOTH,
    DeviceInfo,
    format_mac,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .client import DruFireplaceError, DruStateError
from .const import DOMAIN, MANUFACTURER
from .coordinator import DruFireplaceCoordinator
from .protocol import FireplaceStatus


class DruFireplaceEntity(CoordinatorEntity[DruFireplaceCoordinator]):
    """Common base of all fireplace entities."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: DruFireplaceCoordinator, key: str | None = None
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        mac = format_mac(coordinator.address)
        self._attr_unique_id = f"{mac}_{key}" if key else mac
        identity = coordinator.client.identity
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, mac)},
            connections={(CONNECTION_BLUETOOTH, mac)},
            manufacturer=MANUFACTURER,
            model=identity.fireplace_type or identity.model_number,
            model_id=identity.model_number,
            serial_number=identity.serial_number,
            name=coordinator.config_entry.title,
        )

    @property
    def status(self) -> FireplaceStatus:
        """Return the current status."""
        return self.coordinator.data

    async def _async_send(self, command: Coroutine[Any, Any, None]) -> None:
        """Run a client command and map its errors."""
        try:
            await command
        except DruStateError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="not_burning"
            ) from err
        except DruFireplaceError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err
