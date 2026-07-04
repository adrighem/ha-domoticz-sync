"""Constants for the Domoticz Sync integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "domoticz_sync"

CONF_INCLUDE_HIDDEN = "include_hidden"
CONF_FAVORITE_ONLY = "favorite_only"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_VERIFY_SSL = "verify_ssl"

DEFAULT_NAME = "Domoticz Sync"
DEFAULT_SCAN_INTERVAL = 60
MIN_SCAN_INTERVAL = 10
DEFAULT_URL = "http://localhost:8080"
DEFAULT_VERIFY_SSL = True

DEFAULT_UPDATE_INTERVAL = timedelta(seconds=DEFAULT_SCAN_INTERVAL)
