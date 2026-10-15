"""Tests for the Bluetooth client."""

from __future__ import annotations

from unittest.mock import patch

from bleak.exc import BleakError
import pytest

from custom_components.dru_ble.client import (
    DruAuthenticationError,
    DruConnectionError,
    DruFireplaceClient,
    DruStateError,
    build_service_collection,
)
from custom_components.dru_ble.protocol import (
    CHAR_AUTH_REQUEST,
    CHAR_AUTH_RESPONSE,
    CHAR_ECO,
    CHAR_FLAME,
    CHAR_LOGIN,
    CHAR_STATUS,
    CHAR_TARGET_TEMPERATURE,
    FireplaceStatus,
    auth_request_frame,
    auth_secret_frame,
    login_frame,
)

from . import (
    CHALLENGE,
    MAC,
    STATUS_BURNING,
    STATUS_BURNING_SECOND_BURNER,
    STATUS_OFF,
    STATUS_THERMOSTAT_ECO,
    FakeFireplace,
    make_ble_device,
    make_establish_connection,
    target_temperature_bytes,
)


async def connect(fireplace: FakeFireplace) -> tuple[DruFireplaceClient, list, list]:
    """Connect a client to the fake fireplace."""
    statuses: list[FireplaceStatus] = []
    disconnects: list[bool] = []
    client = DruFireplaceClient(MAC, statuses.append, lambda: disconnects.append(True))
    with patch(
        "custom_components.dru_ble.client.establish_connection",
        side_effect=make_establish_connection(fireplace),
    ):
        await client.async_connect(make_ble_device())
    return client, statuses, disconnects


async def test_connect_authenticates_and_reads() -> None:
    """The handshake runs in the app's order and the status is read."""
    fireplace = FakeFireplace()
    client, statuses, _ = await connect(fireplace)
    assert client.is_connected
    assert fireplace.writes == [
        (CHAR_AUTH_REQUEST, auth_request_frame()),
        (CHAR_LOGIN, login_frame()),
        (CHAR_AUTH_REQUEST, auth_secret_frame(CHALLENGE)),
    ]
    assert CHAR_AUTH_RESPONSE in fireplace.notifications
    assert CHAR_STATUS in fireplace.notifications
    assert client.status is not None
    assert client.status.raw == STATUS_BURNING
    assert client.identity.model_number == "P2025.002 V5"
    assert client.identity.serial_number == "TEST0000000000000001"
    assert client.identity.fireplace_type == "MS75TALL TNNL cer"
    assert statuses == []
    fireplace.status[2] = 50
    fireplace.indicate_status()
    assert statuses[0].flame == 50
    assert client.status.flame == 50


async def test_connect_denied() -> None:
    """A refused login raises and disconnects."""
    fireplace = FakeFireplace(auth_ok=False)
    with pytest.raises(DruAuthenticationError):
        await connect(fireplace)
    assert not fireplace.is_connected


async def test_connect_failure() -> None:
    """Bleak errors become connection errors."""
    client = DruFireplaceClient(MAC, lambda _: None, lambda: None)
    with (
        patch(
            "custom_components.dru_ble.client.establish_connection",
            side_effect=BleakError("no slot"),
        ),
        pytest.raises(DruConnectionError),
    ):
        await client.async_connect(make_ble_device())
    assert not client.is_connected


async def test_commands_preserve_flags() -> None:
    """Flame writes carry the second burner state from the status."""
    fireplace = FakeFireplace(STATUS_BURNING_SECOND_BURNER)
    client, _, _ = await connect(fireplace)
    await client.async_set_flame(50)
    await client.async_set_thermostat_mode(True)
    await client.async_set_second_burner(False)
    await client.async_set_second_burner(True)
    await client.async_set_eco(True)
    await client.async_set_target_temperature(21.5)
    await client.async_turn_off()
    assert fireplace.commands == [
        (CHAR_FLAME, bytes.fromhex("3206")),
        (CHAR_FLAME, bytes.fromhex("fe06")),
        (CHAR_FLAME, bytes.fromhex("ff02")),
        (CHAR_FLAME, bytes.fromhex("ff06")),
        (CHAR_ECO, b"\x01"),
        (CHAR_TARGET_TEMPERATURE, target_temperature_bytes(21.5)),
        (CHAR_FLAME, bytes.fromhex("0000")),
    ]


async def test_manual_mode_writes_current_level() -> None:
    """Leaving thermostat mode writes the current level like the app."""
    fireplace = FakeFireplace(STATUS_THERMOSTAT_ECO)
    client, _, _ = await connect(fireplace)
    await client.async_set_thermostat_mode(False)
    assert fireplace.commands == [(CHAR_FLAME, bytes.fromhex("3406"))]
    fireplace.status[2] = 0
    fireplace.indicate_status()
    await client.async_set_thermostat_mode(False)
    assert fireplace.commands[-1] == (CHAR_FLAME, bytes.fromhex("0106"))


async def test_turn_on_and_state_errors() -> None:
    """Ignition only from off; flame commands only while burning."""
    fireplace = FakeFireplace(STATUS_OFF)
    client, _, _ = await connect(fireplace)
    for command in (
        client.async_set_flame(50),
        client.async_set_thermostat_mode(True),
        client.async_set_second_burner(True),
    ):
        with pytest.raises(DruStateError):
            await command
    assert fireplace.commands == []
    await client.async_turn_on()
    assert fireplace.commands == [(CHAR_FLAME, bytes.fromhex("6402"))]
    await client.async_turn_on()
    assert len(fireplace.commands) == 1


async def test_disconnect_callback() -> None:
    """A dropped link is reported once; a requested disconnect is not."""
    fireplace = FakeFireplace()
    client, _, disconnects = await connect(fireplace)
    fireplace.drop_link()
    assert disconnects == [True]
    assert not client.is_connected
    with pytest.raises(DruConnectionError):
        await client.async_read_status()
    client, _, disconnects = await connect(fireplace)
    await client.async_disconnect()
    assert disconnects == []
    assert not fireplace.is_connected


def test_service_collection() -> None:
    """The seeded table contains the characteristics with their CCCDs."""
    services = build_service_collection()
    status = services.get_characteristic(CHAR_STATUS)
    assert status is not None
    assert status.handle == 0x000F
    assert "indicate" in status.properties
    cccd = status.get_descriptor("00002902-0000-1000-8000-00805f9b34fb")
    assert cccd is not None
    assert cccd.handle == 0x0010
    assert services.get_characteristic(CHAR_AUTH_REQUEST).handle == 0x0078
