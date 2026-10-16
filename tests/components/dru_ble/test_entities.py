"""Tests for the climate, number, switch and sensor entities."""

from __future__ import annotations

import pytest

from custom_components.dru_ble.protocol import (
    CHAR_ECO,
    CHAR_FLAME,
    CHAR_TARGET_TEMPERATURE,
)
from homeassistant.components.climate import (
    ATTR_CURRENT_TEMPERATURE,
    ATTR_HVAC_ACTION,
    ATTR_PRESET_MODE,
    DOMAIN as CLIMATE_DOMAIN,
    SERVICE_SET_HVAC_MODE,
    SERVICE_SET_PRESET_MODE,
    SERVICE_SET_TEMPERATURE,
    HVACAction,
    HVACMode,
)
from homeassistant.components.number import (
    ATTR_VALUE,
    DOMAIN as NUMBER_DOMAIN,
    SERVICE_SET_VALUE,
)
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_TEMPERATURE,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from . import (
    CAPABILITIES_NO_EXTRAS,
    STATUS_BURNING_SECOND_BURNER,
    STATUS_OFF,
    STATUS_OFF_NO_ROOM_TEMPERATURE,
    STATUS_THERMOSTAT_ECO,
    FakeFireplace,
    target_temperature_bytes,
)

CLIMATE = "climate.dfgt_00test00"
FLAME = "number.dfgt_00test00_flame_height"
ECO = "switch.dfgt_00test00_eco_mode"
SECOND_BURNER = "switch.dfgt_00test00_second_burner"
ROOM_TEMPERATURE = "sensor.dfgt_00test00_room_temperature"
OPERATING_STATE = "sensor.dfgt_00test00_operating_state"
LIGHT = "binary_sensor.dfgt_00test00_lamp"


@pytest.mark.usefixtures("setup_entry")
async def test_states_burning(hass: HomeAssistant) -> None:
    """Entities reflect a burning fireplace in manual mode."""
    climate = hass.states.get(CLIMATE)
    assert climate.state == HVACMode.HEAT
    assert climate.attributes[ATTR_HVAC_ACTION] == HVACAction.HEATING
    assert climate.attributes[ATTR_PRESET_MODE] == "manual"
    assert climate.attributes[ATTR_TEMPERATURE] == 23.0
    assert climate.attributes[ATTR_CURRENT_TEMPERATURE] == 21.2
    assert hass.states.get(FLAME).state == "82"
    assert hass.states.get(ECO).state == STATE_OFF
    assert hass.states.get(SECOND_BURNER).state == STATE_OFF
    assert hass.states.get(ROOM_TEMPERATURE).state == "21.21"
    assert hass.states.get(OPERATING_STATE).state == "burning"


@pytest.mark.parametrize("status", [STATUS_THERMOSTAT_ECO])
@pytest.mark.usefixtures("setup_entry")
async def test_states_thermostat_eco(hass: HomeAssistant) -> None:
    """Thermostat mode, eco and second burner show up."""
    climate = hass.states.get(CLIMATE)
    assert climate.attributes[ATTR_PRESET_MODE] == "thermostat"
    assert hass.states.get(ECO).state == STATE_ON
    assert hass.states.get(SECOND_BURNER).state == STATE_ON


@pytest.mark.parametrize("status", [STATUS_OFF_NO_ROOM_TEMPERATURE])
@pytest.mark.usefixtures("setup_entry")
async def test_states_off(hass: HomeAssistant) -> None:
    """An off fireplace has no flame value and no room temperature."""
    climate = hass.states.get(CLIMATE)
    assert climate.state == HVACMode.OFF
    assert climate.attributes[ATTR_HVAC_ACTION] == HVACAction.OFF
    assert climate.attributes[ATTR_CURRENT_TEMPERATURE] is None
    assert hass.states.get(FLAME).state == STATE_UNKNOWN
    assert hass.states.get(ROOM_TEMPERATURE).state == STATE_UNKNOWN
    assert hass.states.get(OPERATING_STATE).state == "off"


@pytest.mark.usefixtures("setup_entry")
async def test_climate_services(hass: HomeAssistant, fireplace: FakeFireplace) -> None:
    """Climate services write the app's commands and the state follows."""
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: CLIMATE, ATTR_TEMPERATURE: 21.5},
        blocking=True,
    )
    assert fireplace.commands[-1] == (
        CHAR_TARGET_TEMPERATURE,
        target_temperature_bytes(21.5),
    )
    assert hass.states.get(CLIMATE).attributes[ATTR_TEMPERATURE] == 21.5

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_PRESET_MODE,
        {ATTR_ENTITY_ID: CLIMATE, ATTR_PRESET_MODE: "thermostat"},
        blocking=True,
    )
    assert fireplace.commands[-1] == (CHAR_FLAME, bytes.fromhex("fe02"))
    assert hass.states.get(CLIMATE).attributes[ATTR_PRESET_MODE] == "thermostat"

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_PRESET_MODE,
        {ATTR_ENTITY_ID: CLIMATE, ATTR_PRESET_MODE: "manual"},
        blocking=True,
    )
    assert fireplace.commands[-1] == (CHAR_FLAME, bytes.fromhex("5202"))
    assert hass.states.get(CLIMATE).attributes[ATTR_PRESET_MODE] == "manual"

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: CLIMATE, "hvac_mode": HVACMode.OFF},
        blocking=True,
    )
    assert fireplace.commands[-1] == (CHAR_FLAME, bytes.fromhex("0000"))
    assert hass.states.get(CLIMATE).state == HVACMode.OFF

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: CLIMATE, "hvac_mode": HVACMode.HEAT},
        blocking=True,
    )
    assert fireplace.commands[-1] == (CHAR_FLAME, bytes.fromhex("6402"))
    assert hass.states.get(CLIMATE).state == HVACMode.HEAT


@pytest.mark.parametrize("status", [STATUS_OFF])
@pytest.mark.usefixtures("setup_entry")
async def test_flame_commands_need_burning(
    hass: HomeAssistant, fireplace: FakeFireplace
) -> None:
    """Preset, flame and second burner refuse while the fireplace is off."""
    for domain, service, data in (
        (CLIMATE_DOMAIN, SERVICE_SET_PRESET_MODE, {ATTR_PRESET_MODE: "thermostat"}),
        (NUMBER_DOMAIN, SERVICE_SET_VALUE, {ATTR_VALUE: 50}),
        (SWITCH_DOMAIN, SERVICE_TURN_ON, {}),
    ):
        entity_id = {
            CLIMATE_DOMAIN: CLIMATE,
            NUMBER_DOMAIN: FLAME,
            SWITCH_DOMAIN: SECOND_BURNER,
        }[domain]
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(
                domain, service, {ATTR_ENTITY_ID: entity_id, **data}, blocking=True
            )
    assert fireplace.commands == []


@pytest.mark.parametrize("status", [STATUS_BURNING_SECOND_BURNER])
@pytest.mark.usefixtures("setup_entry")
async def test_number_and_switches(
    hass: HomeAssistant, fireplace: FakeFireplace
) -> None:
    """Flame and switch writes keep the second burner flag intact."""
    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: FLAME, ATTR_VALUE: 50},
        blocking=True,
    )
    assert fireplace.commands[-1] == (CHAR_FLAME, bytes.fromhex("3206"))
    assert hass.states.get(FLAME).state == "50"

    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: SECOND_BURNER}, blocking=True
    )
    assert fireplace.commands[-1] == (CHAR_FLAME, bytes.fromhex("ff02"))
    assert hass.states.get(SECOND_BURNER).state == STATE_OFF

    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: ECO}, blocking=True
    )
    assert fireplace.commands[-1] == (CHAR_ECO, b"\x01")
    assert hass.states.get(ECO).state == STATE_ON

    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: ECO}, blocking=True
    )
    assert fireplace.commands[-1] == (CHAR_ECO, b"\x00")
    assert hass.states.get(ECO).state == STATE_OFF


@pytest.mark.parametrize("status", [STATUS_OFF])
@pytest.mark.usefixtures("setup_entry")
async def test_light_follows_lamp_key(
    hass: HomeAssistant, fireplace: FakeFireplace
) -> None:
    """The lamp sensor follows relay 1, also while the fireplace is off."""
    assert hass.states.get(LIGHT).state == STATE_OFF
    fireplace.press_light_key()
    await hass.async_block_till_done()
    assert hass.states.get(LIGHT).state == STATE_ON
    fireplace.press_light_key()
    await hass.async_block_till_done()
    assert hass.states.get(LIGHT).state == STATE_OFF
    assert fireplace.commands == []


@pytest.mark.parametrize("capabilities", [CAPABILITIES_NO_EXTRAS])
@pytest.mark.usefixtures("setup_entry")
async def test_missing_equipment_has_no_entities(hass: HomeAssistant) -> None:
    """Without second burner and relay 1 their entities are not created."""
    assert hass.states.get(SECOND_BURNER) is None
    assert hass.states.get(LIGHT) is None
    assert hass.states.get(ECO) is not None


@pytest.mark.parametrize("capabilities", [None])
@pytest.mark.usefixtures("setup_entry")
async def test_unknown_capabilities_keep_entities(hass: HomeAssistant) -> None:
    """If the capabilities cannot be read, all entities are created."""
    assert hass.states.get(SECOND_BURNER) is not None
    assert hass.states.get(LIGHT) is not None
