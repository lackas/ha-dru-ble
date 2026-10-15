"""Config flow for the DRU Fireplace Bluetooth integration."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import voluptuous as vol

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS
from homeassistant.helpers.device_registry import format_mac

from .client import DruAuthenticationError, DruFireplaceClient, DruFireplaceError
from .const import DOMAIN
from .esphome_cache import async_seed_proxy_service_cache
from .protocol import ADVERTISED_SERVICE_UUID, LOCAL_NAME_PREFIX

_LOGGER = logging.getLogger(__name__)

# The remote opens a pairing window of about 3 s after a 5 s key press, so
# the first connection keeps trying for a while.
PAIRING_WINDOW = 60.0


def is_fireplace(info: BluetoothServiceInfoBleak) -> bool:
    """Return True if the advertisement belongs to a DFGT receiver."""
    return info.name.startswith(LOCAL_NAME_PREFIX) or (
        ADVERTISED_SERVICE_UUID in info.service_uuids
    )


class DruFireplaceConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the config flow."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._discovered: dict[str, BluetoothServiceInfoBleak] = {}
        self._connect_task: asyncio.Task[None] | None = None
        self._connect_error: str | None = None

    @property
    def _placeholders(self) -> dict[str, str]:
        assert self._discovery_info is not None
        return {"name": self._discovery_info.name}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle a discovered receiver."""
        await self.async_set_unique_id(format_mac(discovery_info.address))
        self._abort_if_unique_id_configured()
        self._discovery_info = discovery_info
        self.context["title_placeholders"] = self._placeholders
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm the discovered receiver."""
        if user_input is not None:
            return await self.async_step_pair()
        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm", description_placeholders=self._placeholders
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user pick a discovered receiver."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            self._discovery_info = self._discovered[address]
            await self.async_set_unique_id(format_mac(address), raise_on_progress=False)
            self._abort_if_unique_id_configured()
            self.context["title_placeholders"] = self._placeholders
            return await self.async_step_pair()

        configured = self._async_current_ids(include_ignore=False)
        for info in async_discovered_service_info(self.hass, connectable=True):
            if format_mac(info.address) in configured or not is_fireplace(info):
                continue
            self._discovered[info.address] = info
        if not self._discovered:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): vol.In(
                        {
                            address: f"{info.name} ({address})"
                            for address, info in self._discovered.items()
                        }
                    )
                }
            ),
        )

    async def async_step_pair(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Explain the pairing and start the first connection on submit."""
        if user_input is not None:
            return await self.async_step_connect()
        errors = {"base": self._connect_error} if self._connect_error else None
        self._connect_error = None
        self._set_confirm_only()
        return self.async_show_form(
            step_id="pair", description_placeholders=self._placeholders, errors=errors
        )

    async def async_step_connect(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Connect, pair and authenticate once to verify the receiver."""
        if self._connect_task is None:
            self._connect_task = self.hass.async_create_task(self._async_connect())
            # Always show progress first, even if the eager task finished
            # already: the flow manager would otherwise resubmit the pair
            # step with the same input in a loop.
            return self._async_show_connect_progress()
        if not self._connect_task.done():
            return self._async_show_connect_progress()
        try:
            await self._connect_task
        except DruAuthenticationError:
            self._connect_error = "auth_failed"
        except DruFireplaceError as err:
            _LOGGER.debug("Connecting failed: %s", err)
            self._connect_error = "cannot_connect"
        finally:
            self._connect_task = None
        if self._connect_error:
            return self.async_show_progress_done(next_step_id="pair")
        return self.async_show_progress_done(next_step_id="finish")

    def _async_show_connect_progress(self) -> ConfigFlowResult:
        """Show the connection progress."""
        assert self._connect_task is not None
        return self.async_show_progress(
            step_id="connect",
            progress_action="connect",
            progress_task=self._connect_task,
            description_placeholders=self._placeholders,
        )

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create the entry."""
        assert self._discovery_info is not None
        return self.async_create_entry(
            title=self._discovery_info.name,
            data={CONF_ADDRESS: self._discovery_info.address},
        )

    async def _async_connect(self) -> None:
        """Try to connect until it works or the pairing window is over."""
        assert self._discovery_info is not None
        address = self._discovery_info.address
        client = DruFireplaceClient(address, lambda _: None, lambda: None)
        deadline = time.monotonic() + PAIRING_WINDOW
        while True:
            ble_device = (
                bluetooth.async_ble_device_from_address(
                    self.hass, address, connectable=True
                )
                or self._discovery_info.device
            )
            async_seed_proxy_service_cache(self.hass, address)
            try:
                await client.async_connect(ble_device)
            except DruAuthenticationError:
                raise
            except DruFireplaceError:
                if time.monotonic() >= deadline:
                    raise
                await asyncio.sleep(1)
                continue
            await client.async_disconnect()
            return
