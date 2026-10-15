"""Tests for the pure protocol module."""

from __future__ import annotations

import pytest

from custom_components.dru_fireplace.protocol import (
    FLAME_LEVEL_KEEP,
    FLAME_LEVEL_THERMOSTAT,
    IGNITE_COMMAND,
    OFF_COMMAND,
    FireplaceStatus,
    OperatingState,
    auth_request_frame,
    auth_response,
    auth_secret_frame,
    decode_text,
    eco_command,
    flame_command,
    login_frame,
    target_temperature_command,
)

from . import (
    CHALLENGE,
    FIREPLACE_TYPE,
    STATUS_BURNING,
    STATUS_BURNING_SECOND_BURNER,
    STATUS_IGNITING,
    STATUS_OFF,
    STATUS_OFF_NO_ROOM_TEMPERATURE,
    STATUS_THERMOSTAT_ECO,
)


def test_auth_response_matches_capture() -> None:
    """The answer to a captured challenge equals what the app sent."""
    expected = bytes.fromhex(
        "9d060c422a9533e7595526de38af339dcd0e720bdd48c1c680021a3c5f11ee1c"
    )
    assert auth_response(CHALLENGE) == expected
    assert auth_secret_frame(CHALLENGE) == bytes([0x05]) + expected
    assert len(auth_request_frame()) == 33
    assert auth_request_frame()[0] == 0x00
    assert login_frame()[0] == 0x05
    with pytest.raises(ValueError):
        auth_response(b"short")


def test_status_off() -> None:
    """An off fireplace decodes as off."""
    status = FireplaceStatus.from_bytes(STATUS_OFF)
    assert status.operating_state is OperatingState.OFF
    assert not status.is_on
    assert not status.is_burning
    assert status.flame == 0
    assert status.target_temperature == 23.0
    assert status.room_temperature == 21.21


def test_status_burning() -> None:
    """A burning fireplace in manual mode."""
    status = FireplaceStatus.from_bytes(STATUS_BURNING)
    assert status.operating_state is OperatingState.BURNING
    assert status.is_on
    assert status.is_burning
    assert status.flame == 82
    assert not status.second_burner
    assert not status.eco
    assert not status.thermostat_mode
    assert not status.adjusting


def test_status_flags() -> None:
    """Second burner, eco and thermostat bits decode independently."""
    assert FireplaceStatus.from_bytes(STATUS_BURNING_SECOND_BURNER).second_burner
    assert FireplaceStatus.from_bytes(STATUS_IGNITING).operating_state is (
        OperatingState.IGNITING
    )
    assert FireplaceStatus.from_bytes(STATUS_IGNITING).adjusting
    status = FireplaceStatus.from_bytes(STATUS_THERMOSTAT_ECO)
    assert status.is_burning
    assert status.second_burner
    assert status.eco
    assert status.thermostat_mode
    assert status.flame == 52


def test_status_unknown_state_and_implausible_room_temperature() -> None:
    """Unknown states and nonsense temperatures become None."""
    status = FireplaceStatus.from_bytes(STATUS_OFF_NO_ROOM_TEMPERATURE)
    assert status.operating_state is OperatingState.OFF
    assert status.room_temperature is None
    assert status.target_temperature == 23.5
    unknown = FireplaceStatus.from_bytes(bytes([0x07]) + STATUS_OFF[1:])
    assert unknown.operating_state is None
    assert unknown.is_on
    with pytest.raises(ValueError):
        FireplaceStatus.from_bytes(b"\x00" * 10)


def test_commands() -> None:
    """Commands are built exactly like the app sends them."""
    assert flame_command(10, second_burner=True) == bytes.fromhex("0a06")
    assert flame_command(100, second_burner=False) == bytes.fromhex("6402")
    assert flame_command(FLAME_LEVEL_THERMOSTAT, True) == bytes.fromhex("fe06")
    assert flame_command(FLAME_LEVEL_KEEP, False) == bytes.fromhex("ff02")
    assert bytes.fromhex("6402") == IGNITE_COMMAND
    assert bytes.fromhex("0000") == OFF_COMMAND
    assert target_temperature_command(23.0) == bytes.fromhex("0000b841")
    assert eco_command(True) == b"\x01"
    assert eco_command(False) == b"\x00"
    with pytest.raises(ValueError):
        flame_command(0, False)
    with pytest.raises(ValueError):
        flame_command(101, False)


def test_decode_text() -> None:
    """Zero padded strings lose their padding."""
    assert decode_text(FIREPLACE_TYPE) == "MS75TALL TNNL cer"
    assert decode_text(b"P2025.002 V5\0\0\0") == "P2025.002 V5"
