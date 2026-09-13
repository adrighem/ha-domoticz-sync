"""Diagnostics tests for secret redaction and operational statistics."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

pytest.importorskip("homeassistant")
pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.const import CONF_PASSWORD, CONF_URL  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402
from homeassistant.helpers import label_registry as lr  # noqa: E402
from pytest_homeassistant_custom_component.common import (  # noqa: E402
    MockConfigEntry,
)

from custom_components.domoticz_sync.bridge import (  # noqa: E402
    DomoticzBridgeManager,
)
from custom_components.domoticz_sync.const import (  # noqa: E402
    CONF_LINK_ID,
    CONF_PAIRING_KEY,
    DATA_BRIDGE_MANAGER,
    DOMAIN,
    EXPORT_LABEL_NAME,
)
from custom_components.domoticz_sync.coordinator import (  # noqa: E402
    DomoticzData,
    DomoticzRuntimeData,
)
from custom_components.domoticz_sync.diagnostics import (  # noqa: E402
    async_get_config_entry_diagnostics,
)
from custom_components.domoticz_sync.models import (  # noqa: E402
    DomoticzDevice,
    SwitchState,
)


@pytest.mark.asyncio
async def test_diagnostics_redact_all_credentials(hass: HomeAssistant) -> None:
    """Neither config-entry data nor defensive options can expose secrets."""
    password = "test-domoticz-password"
    pairing_key = "A" * 43
    defensive_options_key = "B" * 43
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Domoticz test",
        data={
            CONF_URL: "http://domoticz.test:8080",
            CONF_PASSWORD: password,
            CONF_LINK_ID: "link_test_pairing",
            CONF_PAIRING_KEY: pairing_key,
        },
        options={CONF_PAIRING_KEY: defensive_options_key},
    )

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["entry"][CONF_PASSWORD] != password
    assert diagnostics["entry"][CONF_PAIRING_KEY] != pairing_key
    assert diagnostics["options"][CONF_PAIRING_KEY] != defensive_options_key
    assert diagnostics["entry"][CONF_LINK_ID] == "link_test_pairing"


@pytest.mark.asyncio
async def test_diagnostics_include_import_export_bridge_statistics(
    hass: HomeAssistant,
) -> None:
    """Diagnostics include metrics for imported and exported entities."""
    label_reg = lr.async_get(hass)
    label_reg.async_create(EXPORT_LABEL_NAME)

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Domoticz test",
        data={
            CONF_URL: "http://domoticz.test:8080",
            CONF_PASSWORD: "test-password",
            CONF_LINK_ID: "link_test_pairing",
            CONF_PAIRING_KEY: "A" * 43,
        },
    )

    mock_coordinator = MagicMock()
    mock_coordinator.last_update_success = True
    mock_dev1 = DomoticzDevice(
        idx="1",
        name="Switch 1",
        type="Light/Switch",
        sub_type="Switch",
        switch_type="On/Off",
        data="On",
        status="On",
        last_update=None,
        hardware_name="HW",
        hardware_id=1,
        device_id="0001",
        raw={},
    )
    mock_coordinator.data = DomoticzData(
        devices={"1": mock_dev1},
        metrics={},
        binary_states={},
        switches={"1": SwitchState(is_on=True, name="Switch")},
        buttons={},
    )
    entry.runtime_data = DomoticzRuntimeData(
        api=MagicMock(),
        coordinator=mock_coordinator,
    )

    manager = DomoticzBridgeManager()
    hass.data.setdefault(DOMAIN, {})[DATA_BRIDGE_MANAGER] = manager

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["import_statistics"]["last_update_success"] is True
    assert diagnostics["import_statistics"]["total_devices_count"] == 1
    assert diagnostics["import_statistics"]["controllable_switches_count"] == 1
    assert diagnostics["import_statistics"]["controllable_buttons_count"] == 0
    assert "export_statistics" in diagnostics
    assert "loop_exclusions_count" in diagnostics["export_statistics"]
    assert diagnostics["bridge_statistics"]["active_sessions_count"] == 0
    assert diagnostics["bridge_statistics"]["configured_links_count"] == 0
