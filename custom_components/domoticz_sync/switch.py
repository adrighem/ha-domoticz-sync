"""Switch platform for Domoticz Sync."""

from __future__ import annotations

import time
from typing import Any

from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import DomoticzError
from .coordinator import DomoticzRuntimeData
from .entity import DomoticzEntity
from .models import DomoticzDevice, SwitchState

_DEVICE_CLASS_MAP = {
    "outlet": SwitchDeviceClass.OUTLET,
    "switch": SwitchDeviceClass.SWITCH,
}

_OPTIMISTIC_HOLD_SECONDS = 3.0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Domoticz switches from a config entry."""
    runtime_data: DomoticzRuntimeData = entry.runtime_data
    coordinator = runtime_data.coordinator

    entities: list[DomoticzSwitch] = []
    for device_id, switch_state in coordinator.data.switches.items():
        if switch_state is not None:
            device = coordinator.data.devices[device_id]
            entities.append(DomoticzSwitch(coordinator, entry, device, switch_state))
    async_add_entities(entities)


class DomoticzSwitch(DomoticzEntity, SwitchEntity):
    """Representation of a Domoticz switch."""

    def __init__(
        self,
        coordinator,
        entry: ConfigEntry,
        device: DomoticzDevice,
        initial_state: SwitchState,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, entry, device)
        self._attr_name = initial_state.name
        self._attr_unique_id = f"{entry.entry_id}_{device.idx}_switch"
        self._attr_device_class = _DEVICE_CLASS_MAP.get(
            initial_state.device_class or "switch"
        )
        self._optimistic_is_on: bool | None = None
        self._optimistic_until: float = 0.0

    @property
    def available(self) -> bool:
        """Return if the switch has a current matching state."""
        return super().available and self._switch_state is not None

    @property
    def is_on(self) -> bool | None:
        """Return the switch state, respecting optimistic hold."""
        if (
            self._optimistic_is_on is not None
            and time.monotonic() < self._optimistic_until
        ):
            return self._optimistic_is_on
        switch_state = self._switch_state
        return switch_state.is_on if switch_state is not None else None

    @property
    def _switch_state(self) -> SwitchState | None:
        """Return the current switch state from coordinator data."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.switches.get(self._idx)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        await self._async_send_command("On")

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        await self._async_send_command("Off")

    async def async_toggle(self, **kwargs: Any) -> None:
        """Toggle the switch."""
        target = "Off" if self.is_on else "On"
        await self._async_send_command(target)

    async def _async_send_command(self, command: str) -> None:
        """Send command to Domoticz API with optimistic state hold and rollback."""
        previous_optimistic = self._optimistic_is_on
        previous_until = self._optimistic_until

        self._optimistic_is_on = command == "On"
        self._optimistic_until = time.monotonic() + _OPTIMISTIC_HOLD_SECONDS
        self.async_write_ha_state()

        try:
            await self.coordinator.api.async_switch_command(self._idx, command)
        except DomoticzError as err:
            self._optimistic_is_on = previous_optimistic
            self._optimistic_until = previous_until
            self.async_write_ha_state()
            raise HomeAssistantError(
                f"Failed to turn {command.lower()} Domoticz switch {self._idx}: {err}"
            ) from err
