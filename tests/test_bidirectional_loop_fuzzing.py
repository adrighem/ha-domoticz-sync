"""Bidirectional synchronization and loop fuzzing integration tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("homeassistant")
pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.const import (  # noqa: E402
    ATTR_DEVICE_CLASS,
    CONF_PASSWORD,
    CONF_URL,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.core import HomeAssistant  # noqa: E402
from homeassistant.helpers import entity_registry as er  # noqa: E402
from homeassistant.helpers import label_registry as lr  # noqa: E402
from homeassistant.helpers.instance_id import (  # noqa: E402
    async_get as async_get_instance_id,
)
from homeassistant.setup import async_setup_component  # noqa: E402
from pytest_homeassistant_custom_component.common import (  # noqa: E402
    MockConfigEntry,
)
from pytest_homeassistant_custom_component.typing import (  # noqa: E402
    ClientSessionGenerator,
)

from custom_components.domoticz_sync.bridge import (  # noqa: E402
    DomoticzBridgeManager,
)
from custom_components.domoticz_sync.bridge_reconciliation import (  # noqa: E402
    HomeAssistantExportApplication,
)
from custom_components.domoticz_sync.catalog_storage import (  # noqa: E402
    HomeAssistantBinaryCatalogStorage,
)
from custom_components.domoticz_sync.const import (  # noqa: E402
    CONF_EXPORT_LABEL_ID,
    CONF_LINK_ID,
    CONF_PAIRING_KEY,
    DOMAIN,
    EXPORT_LABEL_NAME,
)
from custom_components.domoticz_sync.core.capabilities import (  # noqa: E402
    Capability,
    CapabilityKind,
    SourceIdentity,
)
from custom_components.domoticz_sync.core.catalog import (  # noqa: E402
    TargetCatalog,
    TargetRecord,
    catalog_to_document,
)
from custom_components.domoticz_sync.core.protocol import (  # noqa: E402
    canonical_json_loads,
    generate_link_id,
    generate_pairing_key,
)
from custom_components.domoticz_sync.core.reconciliation import (  # noqa: E402
    derive_domoticz_target_id,
)
from custom_components.domoticz_sync.home_assistant_source import (  # noqa: E402
    ExportExclusionReason,
    collect_export_selection,
)
from tests.test_plugin_bridge_integration import (  # noqa: E402
    _close_plugin_connection,
    _load_plugin,
    _next_text_payload,
    _ObservedBridgeView,
    _open_plugin_connection,
    _receive_text,
)

_DESTINATION_ID = "00000000-0000-0000-0000-000000000000"


@pytest.mark.asyncio
async def test_bidirectional_sync_loop_prevention_provenance(
    hass: HomeAssistant,
) -> None:
    """Imported Domoticz entities cannot be re-exported even when labelled."""
    label_reg = lr.async_get(hass)
    export_label = label_reg.async_create(EXPORT_LABEL_NAME)

    entity_reg = er.async_get(hass)

    # 1. Native Home Assistant switch
    native_entry = entity_reg.async_get_or_create(
        "switch",
        "native_platform",
        "unique-native-switch",
        suggested_object_id="native_switch",
    )
    entity_reg.async_update_entity(
        native_entry.entity_id, labels={export_label.label_id}
    )
    hass.states.async_set(native_entry.entity_id, STATE_OFF)

    # 2. Imported Domoticz switch (provenance platform: domoticz_sync)
    imported_entry = entity_reg.async_get_or_create(
        "switch",
        DOMAIN,
        "domoticz-imported-idx-42",
        suggested_object_id="domoticz_switch_42",
    )
    entity_reg.async_update_entity(
        imported_entry.entity_id, labels={export_label.label_id}
    )
    hass.states.async_set(imported_entry.entity_id, STATE_ON)

    # 3. Native binary sensor with Domoticz mirror attributes
    mirror_entry = entity_reg.async_get_or_create(
        "binary_sensor",
        "template",
        "mirrored-template-switch",
        suggested_object_id="mirrored_template",
    )
    entity_reg.async_update_entity(
        mirror_entry.entity_id, labels={export_label.label_id}
    )
    hass.states.async_set(
        mirror_entry.entity_id,
        STATE_OFF,
        {"domoticz_idx": 99, ATTR_DEVICE_CLASS: "motion"},
    )

    instance_id = await async_get_instance_id(hass)
    collection = collect_export_selection(
        hass,
        instance_id=instance_id,
        label_id=export_label.label_id,
    )

    # Native entity is exported
    exported_sources = [cap.source.object_id for cap in collection.capabilities]
    assert native_entry.id in exported_sources

    # Domoticz imported and mirrored entities are excluded with DOMOTICZ_MIRROR reason
    exclusions_by_id = {exc.entity_id: exc.reason for exc in collection.exclusions}
    assert (
        exclusions_by_id[imported_entry.entity_id]
        == ExportExclusionReason.DOMOTICZ_MIRROR
    )
    assert (
        exclusions_by_id[mirror_entry.entity_id]
        == ExportExclusionReason.DOMOTICZ_MIRROR
    )


@pytest.mark.asyncio
async def test_simultaneous_bidirectional_command_execution(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both HA-to-Domoticz and Domoticz-to-HA commands execute cleanly."""
    label_registry = lr.async_get(hass)
    export_label = label_registry.async_create(EXPORT_LABEL_NAME)

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Domoticz Bidirectional",
        data={
            CONF_URL: "http://domoticz.local:8080",
            CONF_PASSWORD: "secret-password",
            CONF_LINK_ID: "link_test_bidi",
            CONF_PAIRING_KEY: "P" * 43,
            CONF_EXPORT_LABEL_ID: export_label.label_id,
        },
    )
    entry.add_to_hass(hass)

    registry = er.async_get(hass)
    source_entry = registry.async_get_or_create(
        "switch",
        "demo",
        "bidi-switch-ha",
        suggested_object_id="bidi_ha_switch",
    )
    hass.states.async_set(source_entry.entity_id, STATE_OFF)

    capability = Capability(
        source=SourceIdentity("home_assistant", "inst-1", source_entry.id, "state"),
        kind=CapabilityKind.BINARY,
        name="Bidi HA Switch",
        value=False,
    )
    target_id = derive_domoticz_target_id(capability.source)
    storage = HomeAssistantBinaryCatalogStorage(
        hass,
        entry_id=entry.entry_id,
        destination_id=_DESTINATION_ID,
    )
    await storage.async_save(
        catalog_to_document(TargetCatalog((TargetRecord(target_id, capability),)))
    )

    service_calls = []
    import homeassistant.core

    original_async_call = homeassistant.core.ServiceRegistry.async_call

    async def mock_service_call(
        self, domain, service, service_data, blocking=True, context=None, **kwargs
    ):
        if domain == "homeassistant" and service in {"turn_on", "turn_off"}:
            service_calls.append((domain, service, service_data))
            return None
        return await original_async_call(
            self, domain, service, service_data, blocking, context, **kwargs
        )

    monkeypatch.setattr(
        homeassistant.core.ServiceRegistry, "async_call", mock_service_call
    )

    # Mock Domoticz API client for HA -> Domoticz commands
    mock_api = MagicMock()
    mock_api.async_switch_command = AsyncMock(return_value={"status": "OK"})

    manager = DomoticzBridgeManager(HomeAssistantExportApplication(hass))
    link_id = generate_link_id()
    pairing_key = generate_pairing_key()
    await manager.async_register_link(
        entry_id=entry.entry_id,
        link_id=link_id,
        pairing_key=pairing_key,
    )

    assert await async_setup_component(hass, "http", {})
    bridge_view = _ObservedBridgeView(manager)
    hass.http.register_view(bridge_view)
    client = await hass_client_no_auth()
    endpoint = client.make_url("/")

    plugin_module, fake_domoticz = _load_plugin(
        monkeypatch,
        address=endpoint.host,
        port=endpoint.port,
        link_id=link_id,
        pairing_key=pairing_key,
    )
    fake_domoticz.configuration["domoticz_sync_destination_id"] = _DESTINATION_ID

    (
        plugin,
        connection,
        websocket,
        send_position,
        _inventory,
    ) = await _open_plugin_connection(
        plugin_module,
        fake_domoticz,
        client,
        monkeypatch,
    )

    # 1. HA-to-Domoticz control path
    res = await mock_api.async_switch_command("101", "On")
    assert res == {"status": "OK"}
    mock_api.async_switch_command.assert_called_once_with("101", "On")

    # 2. Domoticz-to-HA control path
    plugin.onCommand(target_id, 1, "On", 0, "")
    control_request, send_position = _next_text_payload(connection, send_position)
    await websocket.send_str(control_request)

    raw_response = await _receive_text(websocket)
    plugin.onMessage(connection, {"Payload": raw_response})

    assert len(service_calls) == 1
    assert service_calls[0] == (
        "homeassistant",
        "turn_on",
        {"entity_id": source_entry.entity_id},
    )
    assert any("confirmed" in status for status in fake_domoticz.statuses)

    await _close_plugin_connection(plugin, websocket, manager, bridge_view, 1)


@pytest.mark.asyncio
async def test_rate_limiting_burst_fuzzing(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bursting commands beyond the rate limit rejects excess commands cleanly."""
    label_registry = lr.async_get(hass)
    export_label = label_registry.async_create(EXPORT_LABEL_NAME)

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Domoticz Burst Test",
        data={
            CONF_URL: "http://domoticz.local:8080",
            CONF_PASSWORD: "secret-password",
            CONF_LINK_ID: "link_test_burst",
            CONF_PAIRING_KEY: "B" * 43,
            CONF_EXPORT_LABEL_ID: export_label.label_id,
        },
    )
    entry.add_to_hass(hass)

    registry = er.async_get(hass)
    source_entry = registry.async_get_or_create(
        "switch",
        "demo",
        "burst-switch-ha",
        suggested_object_id="burst_ha_switch",
    )
    hass.states.async_set(source_entry.entity_id, STATE_OFF)

    capability = Capability(
        source=SourceIdentity("home_assistant", "inst-1", source_entry.id, "state"),
        kind=CapabilityKind.BINARY,
        name="Burst Switch",
        value=False,
    )
    target_id = derive_domoticz_target_id(capability.source)
    storage = HomeAssistantBinaryCatalogStorage(
        hass,
        entry_id=entry.entry_id,
        destination_id=_DESTINATION_ID,
    )
    await storage.async_save(
        catalog_to_document(TargetCatalog((TargetRecord(target_id, capability),)))
    )

    import homeassistant.core

    original_async_call = homeassistant.core.ServiceRegistry.async_call

    async def mock_service_call(
        self, domain, service, service_data, blocking=True, context=None, **kwargs
    ):
        if domain == "homeassistant" and service in {"turn_on", "turn_off"}:
            return None
        return await original_async_call(
            self, domain, service, service_data, blocking, context, **kwargs
        )

    monkeypatch.setattr(
        homeassistant.core.ServiceRegistry, "async_call", mock_service_call
    )

    manager = DomoticzBridgeManager(HomeAssistantExportApplication(hass))
    link_id = generate_link_id()
    pairing_key = generate_pairing_key()
    await manager.async_register_link(
        entry_id=entry.entry_id,
        link_id=link_id,
        pairing_key=pairing_key,
    )

    assert await async_setup_component(hass, "http", {})
    bridge_view = _ObservedBridgeView(manager)
    hass.http.register_view(bridge_view)
    client = await hass_client_no_auth()
    endpoint = client.make_url("/")

    plugin_module, fake_domoticz = _load_plugin(
        monkeypatch,
        address=endpoint.host,
        port=endpoint.port,
        link_id=link_id,
        pairing_key=pairing_key,
    )
    fake_domoticz.configuration["domoticz_sync_destination_id"] = _DESTINATION_ID

    (
        plugin,
        connection,
        websocket,
        send_position,
        _inventory,
    ) = await _open_plugin_connection(
        plugin_module,
        fake_domoticz,
        client,
        monkeypatch,
    )

    # Fire 35 rapid commands (limit is 30 per 5 seconds)
    confirmed_count = 0
    rejected_count = 0

    for i in range(35):
        plugin.onCommand(target_id, 1, "On" if i % 2 == 0 else "Off", 0, "")
        control_request, send_position = _next_text_payload(connection, send_position)
        await websocket.send_str(control_request)

        raw_response = await _receive_text(websocket)
        parsed = canonical_json_loads(raw_response)
        plugin.onMessage(connection, {"Payload": raw_response})

        payload = parsed.get("payload", {})
        if payload.get("status") == "confirmed":
            confirmed_count += 1
        elif payload.get("status") == "rejected":
            rejected_count += 1

    assert confirmed_count == 30
    assert rejected_count == 5
    assert any("rate limit exceeded" in err for err in fake_domoticz.errors)

    await _close_plugin_connection(plugin, websocket, manager, bridge_view, 1)


@pytest.mark.asyncio
async def test_dynamic_label_cycling_fuzzing(
    hass: HomeAssistant,
) -> None:
    """Repeatedly toggling export labels under mutation causes no loop or error."""
    label_registry = lr.async_get(hass)
    export_label = label_registry.async_create(EXPORT_LABEL_NAME)

    registry = er.async_get(hass)
    entities = []
    for i in range(10):
        ent = registry.async_get_or_create(
            "switch",
            "demo",
            f"fuzz-switch-{i}",
            suggested_object_id=f"fuzz_switch_{i}",
        )
        hass.states.async_set(ent.entity_id, STATE_OFF)
        entities.append(ent)

    instance_id = await async_get_instance_id(hass)

    # Perform 20 cycles of random label addition, removal, state changes
    for cycle in range(20):
        # Add labels to even indices, remove from odd
        for idx, ent in enumerate(entities):
            if (idx + cycle) % 2 == 0:
                registry.async_update_entity(
                    ent.entity_id,
                    labels={export_label.label_id},
                )
            else:
                registry.async_update_entity(
                    ent.entity_id,
                    labels=set(),
                )
            hass.states.async_set(
                ent.entity_id,
                STATE_ON if cycle % 2 == 0 else STATE_OFF,
            )

        collection = collect_export_selection(
            hass,
            instance_id=instance_id,
            label_id=export_label.label_id,
        )

        expected_count = sum(1 for idx in range(10) if (idx + cycle) % 2 == 0)
        assert len(collection.capabilities) == expected_count
        assert all(
            cap.source.object_id in {e.id for e in entities}
            for cap in collection.capabilities
        )
