"""Tests for Domoticz button platform."""

from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("homeassistant")
pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.const import CONF_PASSWORD, CONF_URL, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.domoticz_sync.api import DomoticzApi, DomoticzApiError
from custom_components.domoticz_sync.const import CONF_VERIFY_SSL, DOMAIN
from custom_components.domoticz_sync.models import DomoticzDevice


def _button_devices() -> list[DomoticzDevice]:
    """Return test devices containing momentary buttons and non-buttons."""
    return [
        DomoticzDevice.from_api(
            {
                "idx": "30",
                "Name": "Garage Gate Remote",
                "Type": "Light/Switch",
                "SwitchType": "Push On Button",
                "Status": "Off",
                "HardwareName": "RFXCOM",
                "HardwareID": 1,
                "ID": "btn-30",
            }
        ),
        DomoticzDevice.from_api(
            {
                "idx": "31",
                "Name": "Master Off Switch",
                "Type": "Light/Switch",
                "SwitchType": "Push Off Button",
                "Status": "Off",
                "HardwareName": "RFXCOM",
                "HardwareID": 1,
                "ID": "btn-31",
            }
        ),
        DomoticzDevice.from_api(
            {
                "idx": "32",
                "Name": "Front Door Chime",
                "Type": "Light/Switch",
                "SwitchType": "Doorbell",
                "Status": "Off",
                "HardwareName": "RFXCOM",
                "HardwareID": 1,
                "ID": "btn-32",
            }
        ),
        DomoticzDevice.from_api(
            {
                "idx": "33",
                "Name": "Standard Lamp",
                "Type": "Light/Switch",
                "SwitchType": "On/Off",
                "Status": "Off",
                "HardwareName": "RFXCOM",
                "HardwareID": 1,
                "ID": "sw-33",
            }
        ),
    ]


@pytest.mark.asyncio
async def test_button_setup_and_press(
    hass: HomeAssistant,
    enable_custom_integrations: None,
) -> None:
    """Test button platform discovers push buttons and sends correct commands."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Domoticz test",
        unique_id="http://domoticz.test:8080",
        data={
            CONF_URL: "http://domoticz.test:8080",
            CONF_USERNAME: "",
            CONF_PASSWORD: "",
            CONF_VERIFY_SSL: False,
        },
    )
    entry.add_to_hass(hass)

    switch_cmd_mock = AsyncMock(return_value={"status": "OK"})

    with (
        patch.object(
            DomoticzApi,
            "async_get_devices",
            AsyncMock(return_value=_button_devices()),
        ),
        patch.object(
            DomoticzApi,
            "async_switch_command",
            switch_cmd_mock,
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        # Push On button
        assert hass.states.get("button.garage_gate_remote_press") is not None
        await hass.services.async_call(
            "button",
            "press",
            {"entity_id": "button.garage_gate_remote_press"},
            blocking=True,
        )
        switch_cmd_mock.assert_called_with("30", "On")

        # Push Off button
        assert hass.states.get("button.master_off_switch_press") is not None
        await hass.services.async_call(
            "button",
            "press",
            {"entity_id": "button.master_off_switch_press"},
            blocking=True,
        )
        switch_cmd_mock.assert_called_with("31", "Off")

        # Doorbell button
        assert hass.states.get("button.front_door_chime_press") is not None
        await hass.services.async_call(
            "button",
            "press",
            {"entity_id": "button.front_door_chime_press"},
            blocking=True,
        )
        switch_cmd_mock.assert_called_with("32", "On")

        # Standard switch must not become a button
        assert hass.states.get("button.standard_lamp_press") is None

        # Registries
        ent_reg = er.async_get(hass)
        btn_entry = ent_reg.async_get("button.garage_gate_remote_press")
        assert btn_entry is not None
        assert btn_entry.unique_id == f"{entry.entry_id}_30_button"

        dev_reg = dr.async_get(hass)
        device = dev_reg.async_get(btn_entry.device_id)
        assert device is not None
        assert (DOMAIN, entry.entry_id, "1_btn-30") in device.identifiers


@pytest.mark.asyncio
async def test_button_error_handling(
    hass: HomeAssistant,
    enable_custom_integrations: None,
) -> None:
    """Test button error propagation as HomeAssistantError."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Domoticz test",
        unique_id="http://domoticz.test:8080",
        data={
            CONF_URL: "http://domoticz.test:8080",
            CONF_USERNAME: "",
            CONF_PASSWORD: "",
            CONF_VERIFY_SSL: False,
        },
    )
    entry.add_to_hass(hass)

    switch_cmd_mock = AsyncMock(side_effect=DomoticzApiError("Network timeout"))

    with (
        patch.object(
            DomoticzApi,
            "async_get_devices",
            AsyncMock(return_value=_button_devices()),
        ),
        patch.object(
            DomoticzApi,
            "async_switch_command",
            switch_cmd_mock,
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        with pytest.raises(
            HomeAssistantError, match="Failed to trigger Domoticz button"
        ):
            await hass.services.async_call(
                "button",
                "press",
                {"entity_id": "button.garage_gate_remote_press"},
                blocking=True,
            )
