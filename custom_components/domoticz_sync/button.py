"""Button platform for Domoticz Sync."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import DomoticzError
from .coordinator import DomoticzRuntimeData
from .entity import DomoticzEntity
from .models import ButtonState, DomoticzDevice


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Domoticz buttons from a config entry."""
    runtime_data: DomoticzRuntimeData = entry.runtime_data
    coordinator = runtime_data.coordinator

    entities: list[DomoticzButton] = []
    for device_id, button_state in coordinator.data.buttons.items():
        if button_state is not None:
            device = coordinator.data.devices[device_id]
            entities.append(DomoticzButton(coordinator, entry, device, button_state))
    async_add_entities(entities)


class DomoticzButton(DomoticzEntity, ButtonEntity):
    """Representation of a Domoticz momentary button or trigger."""

    def __init__(
        self,
        coordinator,
        entry: ConfigEntry,
        device: DomoticzDevice,
        initial_state: ButtonState,
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator, entry, device)
        self._attr_name = initial_state.name
        self._attr_unique_id = f"{entry.entry_id}_{device.idx}_button"

    @property
    def available(self) -> bool:
        """Return if the button has a current matching state."""
        return super().available and self._button_state is not None

    @property
    def _button_state(self) -> ButtonState | None:
        """Return the current button state from coordinator data."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.buttons.get(self._idx)

    async def async_press(self) -> None:
        """Press the button, triggering the Domoticz command."""
        button_state = self._button_state
        command = button_state.command if button_state is not None else "On"

        try:
            await self.coordinator.api.async_switch_command(self._idx, command)
        except DomoticzError as err:
            raise HomeAssistantError(
                f"Failed to trigger Domoticz button {self._idx}: {err}"
            ) from err
