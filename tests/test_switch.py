"""Tests for Domoticz switch platform."""

import time
from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("homeassistant")
pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.components.switch import SwitchDeviceClass
from homeassistant.const import CONF_PASSWORD, CONF_URL, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.domoticz_sync.api import DomoticzApi, DomoticzApiError
from custom_components.domoticz_sync.const import CONF_VERIFY_SSL, DOMAIN
from custom_components.domoticz_sync.models import DomoticzDevice


def _switch_devices() -> list[DomoticzDevice]:
    """Return test devices containing switches and non-switches."""
    return [
        DomoticzDevice.from_api(
            {
                "idx": "20",
                "Name": "Ceiling Lamp",
                "Type": "Light/Switch",
                "SwitchType": "On/Off",
                "Status": "On",
                "HardwareName": "Zigbee",
                "HardwareID": 1,
                "ID": "sw-20",
            }
        ),
        DomoticzDevice.from_api(
            {
                "idx": "21",
                "Name": "Kitchen Outlet Plug",
                "Type": "Light/Switch",
                "SwitchType": "On/Off",
                "Status": "Off",
                "HardwareName": "Zigbee",
                "HardwareID": 1,
                "ID": "sw-21",
            }
        ),
        DomoticzDevice.from_api(
            {
                "idx": "22",
                "Name": "Front Door",
                "Type": "Light/Switch",
                "SwitchType": "Contact",
                "Status": "Closed",
                "HardwareName": "Zigbee",
                "HardwareID": 1,
                "ID": "cnt-22",
            }
        ),
    ]


@pytest.mark.asyncio
async def test_switch_setup_creates_switch_and_outlet(
    hass: HomeAssistant,
    enable_custom_integrations: None,
) -> None:
    """Test switch platform discovers switches and sets device class."""
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

    with patch.object(
        DomoticzApi,
        "async_get_devices",
        AsyncMock(return_value=_switch_devices()),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        # Switch entity
        lamp_state = hass.states.get("switch.ceiling_lamp_switch")
        assert lamp_state is not None
        assert lamp_state.state == "on"
        assert lamp_state.attributes.get("device_class") == SwitchDeviceClass.SWITCH

        # Outlet entity
        plug_state = hass.states.get("switch.kitchen_outlet_plug_switch")
        assert plug_state is not None
        assert plug_state.state == "off"
        assert plug_state.attributes.get("device_class") == SwitchDeviceClass.OUTLET

        # Contact sensor must not become a switch
        assert hass.states.get("switch.front_door_switch") is None

        # Device registry attachment
        ent_reg = er.async_get(hass)
        lamp_entry = ent_reg.async_get("switch.ceiling_lamp_switch")
        assert lamp_entry is not None
        assert lamp_entry.unique_id == f"{entry.entry_id}_20_switch"

        dev_reg = dr.async_get(hass)
        device = dev_reg.async_get(lamp_entry.device_id)
        assert device is not None
        assert (DOMAIN, entry.entry_id, "1_sw-20") in device.identifiers


@pytest.mark.asyncio
async def test_switch_turn_on_and_off(
    hass: HomeAssistant,
    enable_custom_integrations: None,
) -> None:
    """Test turning a switch on and off calls Domoticz API."""
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
            AsyncMock(return_value=_switch_devices()),
        ),
        patch.object(
            DomoticzApi,
            "async_switch_command",
            switch_cmd_mock,
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        # Turn off lamp
        await hass.services.async_call(
            "switch",
            "turn_off",
            {"entity_id": "switch.ceiling_lamp_switch"},
            blocking=True,
        )
        switch_cmd_mock.assert_called_with("20", "Off")
        assert hass.states.get("switch.ceiling_lamp_switch").state == "off"

        # Turn on plug
        await hass.services.async_call(
            "switch",
            "turn_on",
            {"entity_id": "switch.kitchen_outlet_plug_switch"},
            blocking=True,
        )
        switch_cmd_mock.assert_called_with("21", "On")
        assert hass.states.get("switch.kitchen_outlet_plug_switch").state == "on"

        # Toggle plug
        await hass.services.async_call(
            "switch",
            "toggle",
            {"entity_id": "switch.kitchen_outlet_plug_switch"},
            blocking=True,
        )
        switch_cmd_mock.assert_called_with("21", "Off")
        assert hass.states.get("switch.kitchen_outlet_plug_switch").state == "off"


@pytest.mark.asyncio
async def test_switch_optimistic_hold_prevents_bounce(
    hass: HomeAssistant,
    enable_custom_integrations: None,
) -> None:
    """Test optimistic hold suppresses bounce from stale coordinator poll."""
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

    # Initial device list has lamp ON
    devices = _switch_devices()
    get_devices = AsyncMock(return_value=devices)
    switch_cmd_mock = AsyncMock(return_value={"status": "OK"})

    with (
        patch.object(
            DomoticzApi,
            "async_get_devices",
            get_devices,
        ),
        patch.object(
            DomoticzApi,
            "async_switch_command",
            switch_cmd_mock,
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        # Turn off lamp
        await hass.services.async_call(
            "switch",
            "turn_off",
            {"entity_id": "switch.ceiling_lamp_switch"},
            blocking=True,
        )
        assert hass.states.get("switch.ceiling_lamp_switch").state == "off"

        # Coordinator poll still returns stale status "On" (hardware latency)
        await entry.runtime_data.coordinator.async_refresh()
        await hass.async_block_till_done()

        # State should still be "off" due to optimistic hold window
        assert hass.states.get("switch.ceiling_lamp_switch").state == "off"

        # Fast-forward past the 3-second hold window
        with patch.object(time, "monotonic", return_value=time.monotonic() + 10.0):
            # Refresh again: now it reflects polled state ("on" because stale)
            await entry.runtime_data.coordinator.async_refresh()
            await hass.async_block_till_done()
            assert hass.states.get("switch.ceiling_lamp_switch").state == "on"


@pytest.mark.asyncio
async def test_switch_error_rolls_back_optimistic_state(
    hass: HomeAssistant,
    enable_custom_integrations: None,
) -> None:
    """Test error during command execution rolls back optimistic state."""
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

    switch_cmd_mock = AsyncMock(side_effect=DomoticzApiError("Hardware unreachable"))

    with (
        patch.object(
            DomoticzApi,
            "async_get_devices",
            AsyncMock(return_value=_switch_devices()),
        ),
        patch.object(
            DomoticzApi,
            "async_switch_command",
            switch_cmd_mock,
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        # Plug starts off, try turning on with failing API
        with pytest.raises(HomeAssistantError, match="Failed to turn on"):
            await hass.services.async_call(
                "switch",
                "turn_on",
                {"entity_id": "switch.kitchen_outlet_plug_switch"},
                blocking=True,
            )

        # State must remain "off"
        assert hass.states.get("switch.kitchen_outlet_plug_switch").state == "off"
