"""Provenance helpers for mirrored entities."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from .const import DOMAIN

if TYPE_CHECKING:
    from .models import DomoticzDevice

ATTR_DOMOTICZ_IDX = "domoticz_idx"
ATTR_SYNC_ORIGIN = f"{DOMAIN}_origin"
ATTR_SYNC_SOURCE_ID = f"{DOMAIN}_source_id"

ORIGIN_DOMOTICZ = "domoticz"


def domoticz_provenance_attributes(source_id: str) -> dict[str, str]:
    """Return stable provenance attributes for a Domoticz mirror."""
    return {
        ATTR_DOMOTICZ_IDX: source_id,
        ATTR_SYNC_ORIGIN: ORIGIN_DOMOTICZ,
        ATTR_SYNC_SOURCE_ID: source_id,
    }


def is_domoticz_mirror(
    *,
    platform: str | None,
    attributes: Mapping[str, Any],
) -> bool:
    """Return whether a Home Assistant entity mirrors a Domoticz source."""
    return (
        platform == DOMAIN
        or attributes.get(ATTR_SYNC_ORIGIN) == ORIGIN_DOMOTICZ
        or ATTR_DOMOTICZ_IDX in attributes
    )


def is_sync_plugin_device(device: DomoticzDevice) -> bool:
    """Return whether a Domoticz device is owned by the export companion plugin."""
    if (
        device.device_id
        and device.device_id.startswith("HA")
        and len(device.device_id) == 25
    ):
        return True
    hardware_name = (device.hardware_name or "").lower()
    if "home assistant" in hardware_name and "sync" in hardware_name:
        return True
    hardware_type = str(device.raw.get("HardwareType") or "").lower()
    return "hadomoticzsync" in hardware_type or (
        "home assistant" in hardware_type and "sync" in hardware_type
    )
