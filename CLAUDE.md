# CLAUDE.md

HACS integration for DRU gas fireplaces with the DFGT Bluetooth receiver.
Domain `dru_ble`. Protocol analysis, HCI captures and the standalone test
tools live outside this repo in `~/src/dru` (PROTOCOL.md, AUTH_PROTOCOL.md,
GATT_SERVICES.md, PROXY_CONNECT.md).

## Layout

- `protocol.py` — pure Python: UUIDs, GATT table with handles, status decoding,
  command frames, SHA256 auth. No HA imports.
- `client.py` — bleak-only client: `establish_connection(pair=True)`, auth
  handshake, status indications, commands with second-burner flag preservation.
- `esphome_cache.py` — seeds bleak-esphome's service cache from the GATT table
  (the receiver refuses discovery before the link is encrypted).
- `coordinator.py` — persistent connection, push updates from indications,
  60 s poll as link check, reconnect on drop.
- `climate.py`, `number.py`, `switch.py`, `sensor.py`, `config_flow.py`,
  `diagnostics.py` — HA glue.

## Development

```bash
~/src/venv/hacs/bin/python -m pytest tests/ -q --timeout=30
~/src/venv/hacs/bin/ruff format custom_components/ tests/
~/src/venv/hacs/bin/ruff check custom_components/ tests/
```

The `hacs` venv holds `pytest-homeassistant-custom-component` plus the
requirements of HA's `bluetooth`, `usb` and `esphome` components.

Live check of the HA connection path against the real proxy (read only):
`~/src/venv/hacs/bin/python ~/src/dru/tools/dru_ha_path_test.py`.

## Rules

- Only commands observed from the official app are sent. Nothing is guessed.
- Flame/mode writes must carry the second-burner flag from the current status.
- ESPHome proxies need 2026.10 or newer (Bluedroid pending-open leak before).
- Deploying to the production HA needs Christian's explicit OK.
