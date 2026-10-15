"""Pre-seed the GATT service cache of ESPHome Bluetooth proxies.

The receiver refuses service discovery until the link is encrypted. An
ESPHome proxy discovers the services right after connecting and before it
pairs, unless bleak-esphome already holds the services of the device in
its cache. Seeding that cache from the documented GATT table makes the
proxy connect without discovery, pair (which encrypts the link) and then
use the cached handles. Local adapters pair before connecting and need no
seeding.
"""

from __future__ import annotations

import logging

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant, callback

from .client import build_service_collection

_LOGGER = logging.getLogger(__name__)

_DEFAULT_MTU = 23


@callback
def async_seed_proxy_service_cache(hass: HomeAssistant, address: str) -> None:
    """Seed the service cache of every ESPHome proxy that sees the receiver."""
    address_int = int(address.replace(":", ""), 16)
    for scanner_device in bluetooth.async_scanner_devices_by_address(
        hass, address, connectable=True
    ):
        connector = getattr(scanner_device.scanner, "connector", None)
        client_factory = getattr(connector, "client", None)
        keywords = getattr(client_factory, "keywords", None) or {}
        bluetooth_device = getattr(
            keywords.get("client_data"), "bluetooth_device", None
        )
        cache = getattr(bluetooth_device, "cache", None)
        if cache is None:
            continue
        if cache.get_gatt_services_cache(address_int) is None:
            _LOGGER.debug(
                "Seeding service cache for %s on %s",
                address,
                scanner_device.scanner.source,
            )
            cache.set_gatt_services_cache(address_int, build_service_collection())
        if cache.get_gatt_mtu_cache(address_int) is None:
            cache.set_gatt_mtu_cache(address_int, _DEFAULT_MTU)
