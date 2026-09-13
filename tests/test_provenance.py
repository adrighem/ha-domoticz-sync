"""Tests for mirror provenance and loopback detection."""

from custom_components.domoticz_sync.const import DOMAIN
from custom_components.domoticz_sync.models import DomoticzDevice
from custom_components.domoticz_sync.provenance import (
    ATTR_DOMOTICZ_IDX,
    ATTR_SYNC_ORIGIN,
    ATTR_SYNC_SOURCE_ID,
    ORIGIN_DOMOTICZ,
    domoticz_provenance_attributes,
    is_domoticz_mirror,
    is_sync_plugin_device,
)


def test_builds_domoticz_provenance_attributes():
    """Test mirrors expose their origin and stable source identifier."""
    assert domoticz_provenance_attributes("42") == {
        ATTR_DOMOTICZ_IDX: "42",
        ATTR_SYNC_ORIGIN: ORIGIN_DOMOTICZ,
        ATTR_SYNC_SOURCE_ID: "42",
    }


def test_detects_mirror_by_integration_platform():
    """Test the entity registry platform is the primary loopback signal."""
    assert is_domoticz_mirror(platform=DOMAIN, attributes={})


def test_detects_mirror_by_explicit_provenance():
    """Test provenance survives contexts without registry information."""
    assert is_domoticz_mirror(
        platform=None,
        attributes={ATTR_SYNC_ORIGIN: ORIGIN_DOMOTICZ},
    )


def test_detects_existing_mirror_by_legacy_attribute():
    """Test entities created before provenance was added remain excluded."""
    assert is_domoticz_mirror(
        platform=None,
        attributes={ATTR_DOMOTICZ_IDX: "42"},
    )


def test_does_not_classify_unrelated_entity_as_mirror():
    """Test unrelated Home Assistant entities remain export candidates."""
    assert not is_domoticz_mirror(
        platform="mqtt",
        attributes={ATTR_SYNC_ORIGIN: "home_assistant"},
    )


def test_detects_sync_plugin_device_by_target_device_id():
    """Test devices with HA-prefixed 25-char target IDs are detected."""
    device = DomoticzDevice.from_api(
        {
            "idx": "100",
            "Name": "Exported Sensor",
            "ID": "HA4Z7Y2W8X9V1U3T5R7P9Q2M4",
            "HardwareName": "Dummy",
            "HardwareID": 1,
        }
    )
    assert is_sync_plugin_device(device)


def test_detects_sync_plugin_device_by_hardware_name():
    """Test devices created under Home Assistant Sync hardware are detected."""
    device = DomoticzDevice.from_api(
        {
            "idx": "101",
            "Name": "Exported Switch",
            "ID": "0001",
            "HardwareName": "Home Assistant Domoticz Sync",
            "HardwareID": 5,
        }
    )
    assert is_sync_plugin_device(device)


def test_detects_sync_plugin_device_by_hardware_type():
    """Test devices created by HADomoticzSync plugin type are detected."""
    device = DomoticzDevice.from_api(
        {
            "idx": "102",
            "Name": "Custom Name Export",
            "ID": "0002",
            "HardwareName": "My Custom Bridge",
            "HardwareType": "HADomoticzSync",
            "HardwareID": 6,
        }
    )
    assert is_sync_plugin_device(device)


def test_does_not_classify_regular_domoticz_device_as_plugin_device():
    """Test native Domoticz devices are not misidentified as plugin targets."""
    device = DomoticzDevice.from_api(
        {
            "idx": "103",
            "Name": "Living Room Temp",
            "ID": "0A1B2C",
            "HardwareName": "RFXCOM USB",
            "HardwareType": "RFXtrx433",
            "HardwareID": 2,
        }
    )
    assert not is_sync_plugin_device(device)
