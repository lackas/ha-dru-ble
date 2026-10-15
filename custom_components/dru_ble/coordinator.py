"""Coordinator keeping the connection to the fireplace receiver."""

from __future__ import annotations

import logging

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothReachabilityIntent
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import DruConnectionError, DruFireplaceClient, DruFireplaceError
from .const import DOMAIN, UPDATE_INTERVAL
from .esphome_cache import async_seed_proxy_service_cache
from .protocol import FireplaceStatus

_LOGGER = logging.getLogger(__name__)

type DruFireplaceConfigEntry = ConfigEntry[DruFireplaceCoordinator]


class DruFireplaceCoordinator(DataUpdateCoordinator[FireplaceStatus]):
    """Hold the connection and push status updates to the entities."""

    config_entry: DruFireplaceConfigEntry

    def __init__(self, hass: HomeAssistant, entry: DruFireplaceConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=entry.title,
            update_interval=UPDATE_INTERVAL,
        )
        self.address: str = entry.data[CONF_ADDRESS]
        self.client = DruFireplaceClient(
            self.address, self._async_handle_status, self._async_handle_disconnect
        )

    async def _async_update_data(self) -> FireplaceStatus:
        """Connect if needed and read the status."""
        if not self.client.is_connected:
            await self._async_connect()
        try:
            return await self.client.async_read_status()
        except DruFireplaceError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": str(err)},
            ) from err

    async def _async_connect(self) -> None:
        ble_device = bluetooth.async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )
        if ble_device is None:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="device_not_found",
                translation_placeholders={
                    "address": self.address,
                    "reason": bluetooth.async_address_reachability_diagnostics(
                        self.hass, self.address, BluetoothReachabilityIntent.CONNECTION
                    ),
                },
            )
        async_seed_proxy_service_cache(self.hass, self.address)
        try:
            await self.client.async_connect(ble_device)
        except DruFireplaceError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="connection_failed",
                translation_placeholders={"error": str(err)},
            ) from err

    @callback
    def _async_handle_status(self, status: FireplaceStatus) -> None:
        """Handle a status indication from the receiver."""
        self.async_set_updated_data(status)

    @callback
    def _async_handle_disconnect(self) -> None:
        """Mark the entities unavailable and reconnect."""
        self.async_set_update_error(DruConnectionError("disconnected"))
        self.hass.async_create_task(self.async_request_refresh())

    async def async_shutdown(self) -> None:
        """Stop the coordinator and drop the connection."""
        await super().async_shutdown()
        await self.client.async_disconnect()
