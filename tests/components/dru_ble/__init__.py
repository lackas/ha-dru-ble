"""Tests for the DRU Fireplace Bluetooth integration."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import struct

from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from bleak.exc import BleakError

from custom_components.dru_ble.protocol import (
    ACCESS_LEVEL_USER,
    AUTH_CODE_CHALLENGE,
    AUTH_CODE_GRANTED,
    CHAR_AUTH_REQUEST,
    CHAR_AUTH_RESPONSE,
    CHAR_CAPABILITIES,
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
    OFF_COMMAND,
    auth_response,
)
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak

MAC = "AA:BB:CC:DD:EE:FF"
NAME = "DFGT-00TEST00"

# Status frames captured from the fireplace (target 23.0 °C, room 21.21 °C).
STATUS_OFF = bytes.fromhex("00000000000000140000b84115aea94100")
STATUS_IGNITING = bytes.fromhex("01080000000000140000b84115aea94100")
STATUS_BURNING = bytes.fromhex("03005200000000140000b84115aea94100")
STATUS_BURNING_SECOND_BURNER = bytes.fromhex("04000a00000000140000b84115aea94100")
STATUS_THERMOSTAT_ECO = bytes.fromhex("44203400000000140000b84115aea94100")
# Captured while the fireplace was off and the remote out of reach.
STATUS_OFF_NO_ROOM_TEMPERATURE = bytes.fromhex("00015000640000140000bc41ae47a1c300")
# Burning with the lamp output (relay 1) switched on by the remote's lamp key.
STATUS_BURNING_LIGHT_ON = bytes.fromhex("04016400640000140000bc41a470af4100")

# Capabilities of the author's fireplace: second burner and relay 1.
CAPABILITIES = bytes.fromhex("3e1f0f")
# The same without second burner and relay 1.
CAPABILITIES_NO_EXTRAS = bytes.fromhex("3c100f")

CHALLENGE = bytes.fromhex("a8eccac39dd88e21f8d15b0890c1907c")
MODEL_NUMBER = b"P2025.002 V5\0\0\0\0\0\0\0\0"
SERIAL_NUMBER = b"TEST0000000000000001"
FIREPLACE_TYPE = b"MS75TALL TNNL cer\0$l"


class FakeFireplace:
    """A bleak client that behaves like the fireplace receiver."""

    def __init__(
        self,
        status: bytes = STATUS_BURNING,
        auth_ok: bool = True,
        capabilities: bytes | None = CAPABILITIES,
    ) -> None:
        """Initialize the fake."""
        self.status = bytearray(status)
        self.capabilities = capabilities
        self.auth_ok = auth_ok
        self.writes: list[tuple[str, bytes]] = []
        self.notifications: dict[str, Callable] = {}
        self.is_connected = True
        self.disconnected_callback: Callable | None = None
        self.connect_count = 0

    async def start_notify(self, uuid: str, callback: Callable) -> None:
        """Register an indication callback."""
        self.notifications[uuid] = callback

    async def stop_notify(self, uuid: str) -> None:
        """Remove an indication callback."""
        self.notifications.pop(uuid, None)

    async def read_gatt_char(self, uuid: str) -> bytearray:
        """Return the characteristic value."""
        if uuid == CHAR_CAPABILITIES:
            if self.capabilities is None:
                raise BleakError(f"Characteristic {uuid} was not found")
            return bytearray(self.capabilities)
        values = {
            CHAR_STATUS: bytes(self.status),
            CHAR_MODEL_NUMBER: MODEL_NUMBER,
            CHAR_SERIAL_NUMBER: SERIAL_NUMBER,
            CHAR_FIREPLACE_TYPE: FIREPLACE_TYPE,
        }
        return bytearray(values[uuid])

    async def write_gatt_char(
        self, uuid: str, data: bytes, response: bool = False
    ) -> None:
        """Record the write and react like the receiver."""
        data = bytes(data)
        self.writes.append((uuid, data))
        if uuid == CHAR_LOGIN:
            self._indicate(CHAR_AUTH_RESPONSE, bytes([AUTH_CODE_CHALLENGE]) + CHALLENGE)
        elif uuid == CHAR_AUTH_REQUEST and data[0] == ACCESS_LEVEL_USER:
            granted = self.auth_ok and data[1:] == auth_response(CHALLENGE)
            code = AUTH_CODE_GRANTED if granted else 0x02
            self._indicate(CHAR_AUTH_RESPONSE, bytes([code]) + CHALLENGE)
        elif uuid == CHAR_FLAME:
            self._apply_flame(data)
        elif uuid == CHAR_ECO:
            self.status[0] = (self.status[0] & ~0x40) | (0x40 if data[0] else 0)
            self.indicate_status()
        elif uuid == CHAR_TARGET_TEMPERATURE:
            self.status[8:12] = data
            self.indicate_status()

    async def disconnect(self) -> None:
        """Disconnect on request of the client."""
        self.is_connected = False

    def drop_link(self) -> None:
        """Simulate the receiver dropping the link."""
        self.is_connected = False
        assert self.disconnected_callback is not None
        self.disconnected_callback(self)

    def press_light_key(self) -> None:
        """Toggle relay 1 like the lamp key of the remote control."""
        on = not self.status[1] & 0x01
        self.status[1] = (self.status[1] & ~0x03) | (0x01 if on else 0x00)
        self.status[4] = 100 if on else 0
        self.indicate_status()

    def indicate_status(self) -> None:
        """Send the current status as indication."""
        self._indicate(CHAR_STATUS, bytes(self.status))

    @property
    def commands(self) -> list[tuple[str, bytes]]:
        """Return the writes after the authentication."""
        return [
            (uuid, data)
            for uuid, data in self.writes
            if uuid not in (CHAR_AUTH_REQUEST, CHAR_LOGIN)
        ]

    def _indicate(self, uuid: str, data: bytes) -> None:
        if callback := self.notifications.get(uuid):
            callback(None, bytearray(data))

    def _apply_flame(self, data: bytes) -> None:
        level, flags = data
        if data == OFF_COMMAND:
            self.status[0] = 0x00
            self.status[1] &= ~0x20
        else:
            burner = 0x04 if flags & 0x04 else 0x03
            self.status[0] = (self.status[0] & 0x40) | burner
            if level == FLAME_LEVEL_THERMOSTAT:
                self.status[1] |= 0x20
            elif level != FLAME_LEVEL_KEEP:
                self.status[1] &= ~0x20
                self.status[2] = level
        self.indicate_status()


def make_establish_connection(fireplace: FakeFireplace) -> Callable:
    """Return a replacement for establish_connection handing out the fake."""

    async def _establish_connection(
        client_class, device, name, disconnected_callback=None, pair=False, **kwargs
    ):
        assert pair is True
        # Connecting takes time; yield once so eager tasks do not finish
        # synchronously.
        await asyncio.sleep(0)
        fireplace.connect_count += 1
        fireplace.is_connected = True
        fireplace.disconnected_callback = disconnected_callback
        return fireplace

    return _establish_connection


def make_ble_device() -> BLEDevice:
    """Return a BLEDevice of the fireplace."""
    return BLEDevice(address=MAC, name=NAME, details={"source": "test"})


def make_service_info(
    name: str = NAME, address: str = MAC, fireplace: bool = True
) -> BluetoothServiceInfoBleak:
    """Return the discovery info of the fireplace (or of another device)."""
    advertisement = AdvertisementData(
        local_name=name,
        manufacturer_data={},
        service_data={},
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"] if fireplace else [],
        rssi=-60,
        tx_power=0,
        platform_data=(),
    )
    return BluetoothServiceInfoBleak(
        name=name,
        address=address,
        rssi=-60,
        manufacturer_data={},
        service_data={},
        service_uuids=advertisement.service_uuids,
        source="test",
        connectable=True,
        time=0,
        device=BLEDevice(address=address, name=name, details={"source": "test"}),
        advertisement=advertisement,
        tx_power=0,
    )


def target_temperature_bytes(celsius: float) -> bytes:
    """Return the float32 payload of a target temperature."""
    return struct.pack("<f", celsius)
