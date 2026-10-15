# ha-dru-fireplace

Home Assistant integration for DRU gas fireplaces with the DFGT Bluetooth
receiver (Maestro and Eco Wave models controlled by the DRU Fire app and the
rectangular RCH remote control).

The integration talks to the receiver over Bluetooth Low Energy, either through
a local adapter or through an ESPHome Bluetooth proxy, and keeps the connection
open so that every change made with the remote control or the app shows up in
Home Assistant right away.

Fireplaces with the older DRU/Honeywell Ethernet bridge (BRDG-03EM01, Modbus
TCP) instead of the Bluetooth receiver are covered by
[rhannink/ha-dru-fireplace](https://github.com/rhannink/ha-dru-fireplace).

## Entities

| Entity | What it does |
|---|---|
| Climate | Off / heat (ignition and shutdown), target temperature, room temperature, preset *manual* (flame set by hand) or *thermostat* (the receiver regulates the flame) |
| Number *Flame height* | Flame height in percent; setting it switches back to manual control |
| Switch *Eco mode* | Eco mode, independent of manual/thermostat |
| Switch *Second burner* | Second burner on or off |
| Sensor *Room temperature* | Measured by the remote control; unknown while the remote is out of reach |
| Sensor *Operating state* | off, igniting, burning |

All commands are sent exactly as the official app sends them. The integration
never sends anything that was not observed from the app.

## Requirements

- Home Assistant with the Bluetooth integration.
- A Bluetooth adapter that can bond with the receiver. Tested with an ESPHome
  Bluetooth proxy (ESP32). ESPHome proxies need **ESPHome 2026.10 or newer**;
  older versions leak aborted connection attempts and the bond never succeeds.
- The receiver only allows service discovery on an encrypted link. The
  integration handles this on ESPHome proxies by pre-seeding the proxy's service
  cache with the receiver's known GATT table, so the proxy pairs before it talks
  to the receiver.

## Installation

### HACS

Add this repository as a custom repository (category *Integration*), download
*DRU Fireplace* and restart Home Assistant.

### Manual

Copy `custom_components/dru_fireplace` into the `custom_components` folder of
your Home Assistant configuration and restart.

## Setup

The receiver is discovered automatically (local name `DFGT-…`). Confirm it, or
add the integration by hand and pick the receiver from the list.

The first connection has to bond with the receiver. Switch the fireplace off,
submit the pairing step and then hold the pairing key on the remote control for
five seconds until the display shows `PAIR`. The receiver opens the pairing
window for only a few seconds, so the integration keeps trying for a minute.
Once bonded, the bond lives in the Bluetooth adapter or proxy; a reflashed proxy
has to be paired again.

The fireplace and the app can stay connected at the same time.

## Development

Protocol and client logic live in `protocol.py` (pure Python) and `client.py`
(bleak only); everything else is Home Assistant glue.

```bash
pip install pytest-homeassistant-custom-component ruff
pytest tests/ --timeout=30
ruff check custom_components/ tests/ && ruff format --check custom_components/ tests/
```
