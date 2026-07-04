"""Binary sensor platform for Domoticz Sync."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import DomoticzRuntimeData
from .entity import DomoticzEntity
from .models import BinaryState, DomoticzDevice, extract_binary_state

_DEVICE_CLASS_MAP = {
    "door": BinarySensorDeviceClass.DOOR,
    "lock": BinarySensorDeviceClass.LOCK,
    "moisture": BinarySensorDeviceClass.MOISTURE,
    "motion": BinarySensorDeviceClass.MOTION,
    "occupancy": BinarySensorDeviceClass.OCCUPANCY,
    "safety": BinarySensorDeviceClass.SAFETY,
    "smoke": BinarySensorDeviceClass.SMOKE,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Domoticz binary sensors from a config entry."""
    runtime_data: DomoticzRuntimeData = entry.runtime_data
    coordinator = runtime_data.coordinator

    entities = [
        DomoticzBinarySensor(coordinator, entry, device, binary_state)
        for device in coordinator.data.devices.values()
        if (binary_state := extract_binary_state(device)) is not None
    ]
    async_add_entities(entities)


class DomoticzBinarySensor(DomoticzEntity, BinarySensorEntity):
    """Representation of a Domoticz binary state."""

    def __init__(
        self,
        coordinator,
        entry: ConfigEntry,
        device: DomoticzDevice,
        initial_state: BinaryState,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, entry, device)
        self._attr_name = initial_state.name
        self._attr_unique_id = f"{entry.entry_id}_{device.idx}_state"
        self._attr_device_class = _DEVICE_CLASS_MAP.get(initial_state.device_class)

    @property
    def available(self) -> bool:
        """Return if the binary sensor has a current matching state."""
        return super().available and self._binary_state is not None

    @property
    def is_on(self) -> bool | None:
        """Return the binary sensor state."""
        binary_state = self._binary_state
        return binary_state.is_on if binary_state is not None else None

    @property
    def _binary_state(self) -> BinaryState | None:
        """Return the current binary state from coordinator data."""
        device = self.domoticz_device
        if device is None:
            return None
        return extract_binary_state(device)
