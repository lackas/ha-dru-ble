"""Bluetooth client for the DRU DFGT fireplace receiver.

Depends on bleak only, not on Home Assistant.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
import logging

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.descriptor import BleakGATTDescriptor
from bleak.backends.device import BLEDevice
from bleak.backends.service import BleakGATTService, BleakGATTServiceCollection
from bleak_retry_connector import (
    BLEAK_RETRY_EXCEPTIONS,
    BleakClientWithServiceCache,
    establish_connection,
)

from .protocol import (
    AUTH_CODE_CHALLENGE,
    AUTH_CODE_GRANTED,
    AUTH_CODES_DENIED,
    CCCD_UUID,
    CHALLENGE_LENGTH,
    CHAR_AUTH_REQUEST,
    CHAR_AUTH_RESPONSE,
    CHAR_ECO,
    CHAR_FIREPLACE_TYPE,
    CHAR_FLAME,
    CHAR_LOGIN,
    CHAR_MODEL_NUMBER,
    CHAR_SERIAL_NUMBER,
    CHAR_STATUS,
    CHAR_TARGET_TEMPERATURE,
    FLAME_LEVEL_KEEP,
    FLAME_LEVEL_THERMOSTAT,
    FLAME_MIN,
    GATT_TABLE,
    IGNITE_COMMAND,
    OFF_COMMAND,
    FireplaceStatus,
    auth_request_frame,
    auth_secret_frame,
    decode_text,
    eco_command,
    flame_command,
    login_frame,
    target_temperature_command,
)

_LOGGER = logging.getLogger(__name__)

AUTH_TIMEOUT = 10.0
# ATT default MTU minus the 3 byte write header.
_MAX_WRITE_WITHOUT_RESPONSE = 20


class DruFireplaceError(Exception):
    """Base error of the client."""


class DruConnectionError(DruFireplaceError):
    """The receiver could not be reached or the link dropped."""


class DruAuthenticationError(DruFireplaceError):
    """The receiver did not grant user access."""


class DruStateError(DruFireplaceError):
    """The command is not allowed in the current state."""


@dataclass(frozen=True, slots=True)
class DruIdentity:
    """Identity read from the receiver."""

    model_number: str | None = None
    serial_number: str | None = None
    fireplace_type: str | None = None


def build_service_collection() -> BleakGATTServiceCollection:
    """Build bleak's service collection from the documented GATT table."""
    services = BleakGATTServiceCollection()
    for service in GATT_TABLE:
        bleak_service = BleakGATTService(None, service.handle, service.uuid)
        services.add_service(bleak_service)
        for characteristic in service.characteristics:
            bleak_characteristic = BleakGATTCharacteristic(
                None,
                characteristic.handle,
                characteristic.uuid,
                list(characteristic.properties),  # type: ignore[arg-type]
                lambda: _MAX_WRITE_WITHOUT_RESPONSE,
                bleak_service,
            )
            services.add_characteristic(bleak_characteristic)
            if characteristic.cccd_handle is not None:
                services.add_descriptor(
                    BleakGATTDescriptor(
                        None,
                        characteristic.cccd_handle,
                        CCCD_UUID,
                        bleak_characteristic,
                    )
                )
    return services


class DruFireplaceClient:
    """Connection to one fireplace receiver.

    The connection is kept open: the receiver indicates every status change,
    which is how changes made with the remote control show up immediately.
    """

    def __init__(
        self,
        address: str,
        status_callback: Callable[[FireplaceStatus], None],
        disconnected_callback: Callable[[], None],
    ) -> None:
        """Initialize the client."""
        self._address = address
        self._status_callback = status_callback
        self._disconnected_callback = disconnected_callback
        self._client: BleakClient | None = None
        self._lock = asyncio.Lock()
        self._status: FireplaceStatus | None = None
        self._identity = DruIdentity()

    @property
    def is_connected(self) -> bool:
        """Return True while connected and authenticated."""
        return self._client is not None and self._client.is_connected

    @property
    def status(self) -> FireplaceStatus | None:
        """Return the last status received."""
        return self._status

    @property
    def identity(self) -> DruIdentity:
        """Return the identity read from the receiver."""
        return self._identity

    async def async_connect(self, ble_device: BLEDevice) -> None:
        """Connect, pair if needed, authenticate and subscribe to the status."""
        async with self._lock:
            if self.is_connected:
                return
            name = ble_device.name or self._address
            try:
                client = await establish_connection(
                    BleakClientWithServiceCache,
                    ble_device,
                    name,
                    disconnected_callback=self._handle_disconnect,
                    pair=True,
                )
            except BLEAK_RETRY_EXCEPTIONS as err:
                raise DruConnectionError(f"{name}: connection failed: {err}") from err
            try:
                await self._async_authenticate(client)
                await client.start_notify(CHAR_STATUS, self._handle_status)
                self._identity = await self._async_read_identity(client)
                self._status = FireplaceStatus.from_bytes(
                    await client.read_gatt_char(CHAR_STATUS)
                )
            except DruFireplaceError:
                await client.disconnect()
                raise
            except (*BLEAK_RETRY_EXCEPTIONS, ValueError) as err:
                await client.disconnect()
                raise DruConnectionError(f"{name}: setup failed: {err}") from err
            self._client = client
            _LOGGER.debug("%s: connected, status %s", name, self._status.raw.hex())

    async def async_disconnect(self) -> None:
        """Disconnect from the receiver."""
        async with self._lock:
            client = self._client
            self._client = None
            if client is not None and client.is_connected:
                await client.disconnect()

    async def async_read_status(self) -> FireplaceStatus:
        """Read the status characteristic."""
        client = self._require_client()
        try:
            data = await client.read_gatt_char(CHAR_STATUS)
            status = FireplaceStatus.from_bytes(data)
        except (*BLEAK_RETRY_EXCEPTIONS, ValueError) as err:
            raise DruConnectionError(f"reading the status failed: {err}") from err
        self._status = status
        return status

    async def async_turn_on(self) -> None:
        """Ignite the fireplace (full flame, like the app)."""
        if self._require_status().is_on:
            return
        await self._async_write(CHAR_FLAME, IGNITE_COMMAND)

    async def async_turn_off(self) -> None:
        """Switch the fireplace off."""
        await self._async_write(CHAR_FLAME, OFF_COMMAND)

    async def async_set_target_temperature(self, celsius: float) -> None:
        """Set the target temperature in °C."""
        await self._async_write(
            CHAR_TARGET_TEMPERATURE, target_temperature_command(celsius)
        )

    async def async_set_flame(self, level: int) -> None:
        """Set the flame height in percent; this also ends thermostat mode."""
        status = self._require_burning()
        await self._async_write(CHAR_FLAME, flame_command(level, status.second_burner))

    async def async_set_thermostat_mode(self, enabled: bool) -> None:
        """Let the receiver control the flame, or return to manual control."""
        status = self._require_burning()
        level = FLAME_LEVEL_THERMOSTAT if enabled else max(status.flame, FLAME_MIN)
        await self._async_write(CHAR_FLAME, flame_command(level, status.second_burner))

    async def async_set_second_burner(self, enabled: bool) -> None:
        """Switch the second burner."""
        self._require_burning()
        await self._async_write(CHAR_FLAME, flame_command(FLAME_LEVEL_KEEP, enabled))

    async def async_set_eco(self, enabled: bool) -> None:
        """Switch eco mode."""
        await self._async_write(CHAR_ECO, eco_command(enabled))

    def _require_client(self) -> BleakClient:
        if self._client is None or not self._client.is_connected:
            raise DruConnectionError("not connected")
        return self._client

    def _require_status(self) -> FireplaceStatus:
        if self._status is None:
            raise DruConnectionError("no status received yet")
        return self._status

    def _require_burning(self) -> FireplaceStatus:
        status = self._require_status()
        if not status.is_burning:
            raise DruStateError("the fireplace is not burning")
        return status

    async def _async_write(self, uuid: str, data: bytes) -> None:
        client = self._require_client()
        _LOGGER.debug("%s: write %s = %s", self._address, uuid[:8], data.hex())
        try:
            await client.write_gatt_char(uuid, data, response=True)
        except BLEAK_RETRY_EXCEPTIONS as err:
            raise DruConnectionError(f"write failed: {err}") from err

    async def _async_authenticate(self, client: BleakClient) -> None:
        """Run the SHA256 challenge-response the app uses."""
        loop = asyncio.get_running_loop()
        challenge: asyncio.Future[bytes] = loop.create_future()
        granted: asyncio.Future[None] = loop.create_future()

        def _on_auth_response(_: BleakGATTCharacteristic, data: bytearray) -> None:
            if not data:
                return
            code, payload = data[0], bytes(data[1:])
            if code == AUTH_CODE_CHALLENGE and not challenge.done():
                challenge.set_result(payload[:CHALLENGE_LENGTH])
            elif code == AUTH_CODE_GRANTED and not granted.done():
                granted.set_result(None)
            elif code in AUTH_CODES_DENIED and not granted.done():
                granted.set_exception(
                    DruAuthenticationError(f"access denied (code 0x{code:02x})")
                )

        try:
            await client.start_notify(CHAR_AUTH_RESPONSE, _on_auth_response)
            await client.write_gatt_char(
                CHAR_AUTH_REQUEST, auth_request_frame(), response=True
            )
            await client.write_gatt_char(CHAR_LOGIN, login_frame(), response=True)
            try:
                async with asyncio.timeout(AUTH_TIMEOUT):
                    challenge_bytes = await challenge
            except TimeoutError as err:
                raise DruAuthenticationError("no challenge received") from err
            await client.write_gatt_char(
                CHAR_AUTH_REQUEST, auth_secret_frame(challenge_bytes), response=True
            )
            try:
                async with asyncio.timeout(AUTH_TIMEOUT):
                    await granted
            except TimeoutError as err:
                raise DruAuthenticationError("access not granted") from err
        except BLEAK_RETRY_EXCEPTIONS as err:
            raise DruConnectionError(f"authentication failed: {err}") from err

    async def _async_read_identity(self, client: BleakClient) -> DruIdentity:
        values: dict[str, str | None] = {}
        for key, uuid in (
            ("model_number", CHAR_MODEL_NUMBER),
            ("serial_number", CHAR_SERIAL_NUMBER),
            ("fireplace_type", CHAR_FIREPLACE_TYPE),
        ):
            try:
                values[key] = decode_text(await client.read_gatt_char(uuid)) or None
            except BLEAK_RETRY_EXCEPTIONS as err:
                _LOGGER.debug("%s: reading %s failed: %s", self._address, key, err)
                values[key] = None
        return DruIdentity(**values)

    def _handle_status(self, _: BleakGATTCharacteristic, data: bytearray) -> None:
        try:
            status = FireplaceStatus.from_bytes(data)
        except ValueError as err:
            _LOGGER.debug("%s: ignoring status: %s", self._address, err)
            return
        self._status = status
        self._status_callback(status)

    def _handle_disconnect(self, client: BleakClient) -> None:
        if client is not self._client:
            # A connection that never completed its setup.
            return
        _LOGGER.debug("%s: disconnected", self._address)
        self._client = None
        self._disconnected_callback()
