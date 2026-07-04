"""Data coordinator for Domoticz Sync."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_URL, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import DomoticzApi, DomoticzAuthError, DomoticzConnectionError, DomoticzError
from .const import (
    CONF_FAVORITE_ONLY,
    CONF_INCLUDE_HIDDEN,
    CONF_SCAN_INTERVAL,
    CONF_VERIFY_SSL,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
)
from .models import (
    BinaryState,
    DomoticzDevice,
    DomoticzMetric,
    extract_binary_state,
    extract_sensor_metrics,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class DomoticzData:
    """Latest Domoticz data snapshot."""

    devices: dict[str, DomoticzDevice]
    metrics: dict[str, list[DomoticzMetric]]
    binary_states: dict[str, BinaryState | None]


@dataclass(slots=True)
class DomoticzRuntimeData:
    """Runtime objects for a Domoticz config entry."""

    api: DomoticzApi
    coordinator: DomoticzDataUpdateCoordinator


class DomoticzDataUpdateCoordinator(DataUpdateCoordinator[DomoticzData]):
    """Fetch Domoticz devices on a shared polling interval."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api: DomoticzApi,
    ) -> None:
        """Initialize the coordinator."""
        interval = int(entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=interval),
            config_entry=entry,
        )
        self.entry = entry
        self.api = api

    @property
    def base_url(self) -> str:
        """Return the Domoticz base URL."""
        return self.api.base_url

    async def _async_update_data(self) -> DomoticzData:
        """Fetch data from Domoticz."""
        try:
            devices = await self.api.async_get_devices(
                include_hidden=bool(self.entry.options.get(CONF_INCLUDE_HIDDEN, False)),
                favorite_only=bool(self.entry.options.get(CONF_FAVORITE_ONLY, False)),
            )
        except DomoticzAuthError as err:
            raise ConfigEntryAuthFailed("Domoticz authentication failed") from err
        except (DomoticzConnectionError, DomoticzError) as err:
            raise UpdateFailed(str(err)) from err

        devices_dict = {device.idx: device for device in devices}
        metrics_dict = {
            device.idx: extract_sensor_metrics(device) for device in devices
        }
        binary_states_dict = {
            device.idx: extract_binary_state(device) for device in devices
        }

        return DomoticzData(
            devices=devices_dict,
            metrics=metrics_dict,
            binary_states=binary_states_dict,
        )


def build_api(hass: HomeAssistant, entry: ConfigEntry) -> DomoticzApi:
    """Build a Domoticz API client from a config entry."""
    session = async_get_clientsession(
        hass, verify_ssl=entry.data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)
    )
    return DomoticzApi(
        session,
        entry.data[CONF_URL],
        entry.data.get(CONF_USERNAME),
        entry.data.get(CONF_PASSWORD),
    )
