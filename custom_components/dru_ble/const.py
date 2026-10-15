"""Constants for the DRU Fireplace Bluetooth integration."""

from datetime import timedelta

DOMAIN = "dru_ble"
MANUFACTURER = "DRU"

# The receiver stores any float, the limits of the app are not known.
MIN_TARGET_TEMPERATURE = 5.0
MAX_TARGET_TEMPERATURE = 30.0

PRESET_MANUAL = "manual"
PRESET_THERMOSTAT = "thermostat"

# Status changes arrive as indications; the poll only verifies the link.
UPDATE_INTERVAL = timedelta(seconds=60)
