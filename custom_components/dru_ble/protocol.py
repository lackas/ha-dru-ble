"""BLE protocol of the DRU DFGT fireplace receiver.

Pure Python, no Home Assistant imports, so it can be tested on its own.
Reconstructed from the official DRU Fire app and verified against the
author's own fireplace (see PROTOCOL.md and AUTH_PROTOCOL.md in the
project directory).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import struct

_CHARACTERISTIC_BASE = "cafe-4bed-a517-6aeeba9eeaca"
_SERVICE_BASE = "cafe-429f-9150-4bf2a5ed8308"


def _characteristic(prefix: str) -> str:
    return f"{prefix}-{_CHARACTERISTIC_BASE}"


def _service(prefix: str) -> str:
    return f"{prefix}-{_SERVICE_BASE}"


# Advertisement: 16-bit service UUID 0xFFF0 plus local name "DFGT-<id>".
ADVERTISED_SERVICE_UUID = "0000fff0-0000-1000-8000-00805f9b34fb"
LOCAL_NAME_PREFIX = "DFGT"

SERVICE_CONTROL = _service("55001000")
SERVICE_FIREPLACE_TYPE = _service("5500c000")
SERVICE_CLIENT = _service("5500ee00")
SERVICE_DEVICE_INFORMATION = "0000180a-0000-1000-8000-00805f9b34fb"

CHAR_STATUS = _characteristic("00002430")
CHAR_CAPABILITIES = _characteristic("10002430")
CHAR_TARGET_TEMPERATURE = _characteristic("00002309")
CHAR_FLAME = _characteristic("00002431")
CHAR_ECO = _characteristic("00002432")
CHAR_FIREPLACE_TYPE = _characteristic("0000c000")
CHAR_LOGIN = _characteristic("0000fe10")
CHAR_AUTH_RESPONSE = _characteristic("0000fe14")
CHAR_AUTH_REQUEST = _characteristic("0000fe1f")
CHAR_MODEL_NUMBER = "00002a24-0000-1000-8000-00805f9b34fb"
CHAR_SERIAL_NUMBER = "00002a25-0000-1000-8000-00805f9b34fb"
CCCD_UUID = "00002902-0000-1000-8000-00805f9b34fb"


@dataclass(frozen=True, slots=True)
class GattCharacteristic:
    """A characteristic of the receiver's GATT table."""

    handle: int
    uuid: str
    properties: tuple[str, ...]
    cccd_handle: int | None = None


@dataclass(frozen=True, slots=True)
class GattService:
    """A service of the receiver's GATT table."""

    handle: int
    uuid: str
    characteristics: tuple[GattCharacteristic, ...]


# The part of the GATT table this integration uses, with the attribute
# handles taken from the service discovery of the official app. The
# receiver refuses service discovery on an unencrypted link, so the
# table is also used to pre-seed the service cache of ESPHome proxies.
GATT_TABLE: tuple[GattService, ...] = (
    GattService(
        0x000D,
        SERVICE_CONTROL,
        (
            GattCharacteristic(0x000F, CHAR_STATUS, ("read", "indicate"), 0x0010),
            GattCharacteristic(0x0012, CHAR_TARGET_TEMPERATURE, ("write",)),
            GattCharacteristic(0x0016, CHAR_FLAME, ("write",)),
            GattCharacteristic(0x001E, CHAR_ECO, ("write",)),
            GattCharacteristic(0x0020, CHAR_CAPABILITIES, ("read", "indicate"), 0x0021),
        ),
    ),
    GattService(
        0x0052,
        SERVICE_DEVICE_INFORMATION,
        (
            GattCharacteristic(0x0054, CHAR_MODEL_NUMBER, ("read",)),
            GattCharacteristic(0x0056, CHAR_SERIAL_NUMBER, ("read",)),
        ),
    ),
    GattService(
        0x005B,
        SERVICE_FIREPLACE_TYPE,
        (
            GattCharacteristic(
                0x005D, CHAR_FIREPLACE_TYPE, ("read", "write", "indicate"), 0x005E
            ),
        ),
    ),
    GattService(
        0x006A,
        SERVICE_CLIENT,
        (
            GattCharacteristic(0x0073, CHAR_LOGIN, ("write",)),
            GattCharacteristic(0x0075, CHAR_AUTH_RESPONSE, ("indicate",), 0x0076),
            GattCharacteristic(0x0078, CHAR_AUTH_REQUEST, ("write",)),
        ),
    ),
)

# ---------------------------------------------------------------------------
# User-level authentication (SHA256 challenge-response)
# ---------------------------------------------------------------------------

# Both constants are compiled into the official app and identical for every
# installation. The client authenticates exactly like the app does.
AUTH_SALT = bytes.fromhex("432732ec50b2bed0227e7772a851711f")
CLIENT_ID = bytes.fromhex("1ec13bd49d944e550e208f3f5dea3aa4")
ACCESS_LEVEL_USER = 0x05

AUTH_CODE_CHALLENGE = 0x01
AUTH_CODE_GRANTED = 0x04
AUTH_CODE_REGISTERED = 0x06
AUTH_CODES_DENIED = frozenset({0x02, 0x03, 0x05})
CHALLENGE_LENGTH = 16


def auth_request_frame(client_id: bytes = CLIENT_ID) -> bytes:
    """Return the registration frame written to the auth request characteristic."""
    return bytes([0x00]) + client_id + bytes(16)


def login_frame(client_id: bytes = CLIENT_ID) -> bytes:
    """Return the login frame written to the login characteristic."""
    return bytes([ACCESS_LEVEL_USER]) + client_id


def auth_response(challenge: bytes, client_id: bytes = CLIENT_ID) -> bytes:
    """Return the 32 byte answer to the receiver's challenge."""
    if len(challenge) != CHALLENGE_LENGTH:
        raise ValueError("challenge must be 16 bytes")
    message = AUTH_SALT + bytes([ACCESS_LEVEL_USER]) + client_id + challenge + client_id
    return hashlib.sha256(message).digest()


def auth_secret_frame(challenge: bytes, client_id: bytes = CLIENT_ID) -> bytes:
    """Return the frame carrying the challenge answer."""
    return bytes([ACCESS_LEVEL_USER]) + auth_response(challenge, client_id)


# ---------------------------------------------------------------------------
# Status (characteristic 00002430, 17 bytes, indicated on change)
# ---------------------------------------------------------------------------

STATUS_MIN_LENGTH = 16
# The receiver reports nonsense (for example -322 °C) while the remote
# control, which measures the room, is out of reach.
_PLAUSIBLE_TEMPERATURE = (-50.0, 100.0)

_STATE_MASK = 0x0F
_STATE_OFF = 0x00
_STATE_IGNITING = 0x01
_STATE_BURNING = 0x03
_STATE_BURNING_SECOND_BURNER = 0x04
_STATE_ECO_BIT = 0x40

_FLAG_ADJUSTING = 0x08
_FLAG_THERMOSTAT = 0x20
# Relay 1, which the remote's lamp key switches. The app reads it as
# "lightStatus"; 1 means on.
_LIGHT_STATUS_MASK = 0x03
_LIGHT_STATUS_ON = 0x01

_CAPABILITY_SECOND_BURNER = 0x02
_CAPABILITY_LIGHT_MASK = 0x0F


class OperatingState(StrEnum):
    """Operating state of the fireplace."""

    OFF = "off"
    IGNITING = "igniting"
    BURNING = "burning"


@dataclass(frozen=True, slots=True)
class FireplaceStatus:
    """Decoded status of the fireplace."""

    raw: bytes
    state: int
    flags: int
    flame: int
    target_temperature: float
    room_temperature: float | None

    @classmethod
    def from_bytes(cls, data: bytes) -> FireplaceStatus:
        """Decode a status frame."""
        if len(data) < STATUS_MIN_LENGTH:
            raise ValueError(f"status frame too short: {data.hex()}")
        target, room = struct.unpack_from("<ff", data, 8)
        low, high = _PLAUSIBLE_TEMPERATURE
        return cls(
            raw=bytes(data),
            state=data[0],
            flags=data[1],
            flame=data[2],
            target_temperature=round(target, 2),
            room_temperature=round(room, 2) if low <= room <= high else None,
        )

    @property
    def operating_state(self) -> OperatingState | None:
        """Return the operating state, None for values never observed."""
        state = self.state & _STATE_MASK
        if state == _STATE_OFF:
            return OperatingState.OFF
        if state == _STATE_IGNITING:
            return OperatingState.IGNITING
        if state in (_STATE_BURNING, _STATE_BURNING_SECOND_BURNER):
            return OperatingState.BURNING
        return None

    @property
    def is_on(self) -> bool:
        """Return True unless the fireplace is off."""
        return (self.state & _STATE_MASK) != _STATE_OFF

    @property
    def is_burning(self) -> bool:
        """Return True while the burner is lit."""
        return self.operating_state is OperatingState.BURNING

    @property
    def second_burner(self) -> bool:
        """Return True if the second burner is on."""
        return (self.state & _STATE_MASK) == _STATE_BURNING_SECOND_BURNER

    @property
    def eco(self) -> bool:
        """Return True if eco mode is on."""
        return bool(self.state & _STATE_ECO_BIT)

    @property
    def thermostat_mode(self) -> bool:
        """Return True if the flame follows the target temperature."""
        return bool(self.flags & _FLAG_THERMOSTAT)

    @property
    def adjusting(self) -> bool:
        """Return True while the burner is changing state."""
        return bool(self.flags & _FLAG_ADJUSTING)

    @property
    def light(self) -> bool:
        """Return True if relay 1, the lamp output, is on."""
        return (self.flags & _LIGHT_STATUS_MASK) == _LIGHT_STATUS_ON


@dataclass(frozen=True, slots=True)
class FireplaceCapabilities:
    """What the fireplace is equipped with, decoded like the app does."""

    raw: bytes

    @classmethod
    def from_bytes(cls, data: bytes) -> FireplaceCapabilities:
        """Decode the capabilities characteristic."""
        if len(data) < 2:
            raise ValueError(f"capabilities too short: {data.hex()}")
        return cls(raw=bytes(data))

    @property
    def second_burner(self) -> bool:
        """Return True if the fireplace has a second burner."""
        return bool(self.raw[0] & _CAPABILITY_SECOND_BURNER)

    @property
    def light(self) -> bool:
        """Return True if relay 1 (lamp output) is available."""
        return bool(self.raw[1] & _CAPABILITY_LIGHT_MASK)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

FLAME_MIN = 1
FLAME_MAX = 100
FLAME_LEVEL_KEEP = 0xFF
FLAME_LEVEL_THERMOSTAT = 0xFE

_FLAG_BURNER_ON = 0x02
_FLAG_SECOND_BURNER = 0x04

# Ignition and shutdown exactly as the app sends them.
IGNITE_COMMAND = bytes([FLAME_MAX, _FLAG_BURNER_ON])
OFF_COMMAND = bytes([0x00, 0x00])


def flame_command(level: int, second_burner: bool) -> bytes:
    """Return the flame/mode command: [level][flags].

    The flags carry the second burner state, so callers must pass the
    current state or they switch the second burner by accident.
    """
    if level not in (FLAME_LEVEL_KEEP, FLAME_LEVEL_THERMOSTAT) and not (
        FLAME_MIN <= level <= FLAME_MAX
    ):
        raise ValueError(f"flame level out of range: {level}")
    flags = _FLAG_BURNER_ON | (_FLAG_SECOND_BURNER if second_burner else 0)
    return bytes([level, flags])


def target_temperature_command(celsius: float) -> bytes:
    """Return the target temperature command (float32, little endian)."""
    return struct.pack("<f", celsius)


def eco_command(enabled: bool) -> bytes:
    """Return the eco mode command."""
    return bytes([0x01 if enabled else 0x00])


def decode_text(data: bytes) -> str:
    """Decode a zero padded text characteristic."""
    return bytes(data).split(b"\0", 1)[0].decode("ascii", "replace").strip()
