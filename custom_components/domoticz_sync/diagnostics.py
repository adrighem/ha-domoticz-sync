"""Diagnostics support for Domoticz Sync."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers.instance_id import async_get as async_get_instance_id

from .const import CONF_PAIRING_KEY, DATA_BRIDGE_MANAGER, DOMAIN
from .home_assistant_source import (
    ExportLabelNotFoundError,
    collect_export_selection,
)

TO_REDACT = {CONF_PASSWORD, CONF_PAIRING_KEY}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    data: dict[str, Any] = {
        "entry": async_redact_data(entry.data, TO_REDACT),
        "options": async_redact_data(entry.options, TO_REDACT),
    }

    # Coordinator and import statistics
    runtime_data = getattr(entry, "runtime_data", None)
    if (
        runtime_data is not None
        and getattr(runtime_data, "coordinator", None) is not None
    ):
        coordinator = runtime_data.coordinator
        coord_data = getattr(coordinator, "data", None)
        devices = getattr(coord_data, "devices", {}) if coord_data else {}
        switches = getattr(coord_data, "switches", {}) if coord_data else {}
        buttons = getattr(coord_data, "buttons", {}) if coord_data else {}
        data["import_statistics"] = {
            "last_update_success": coordinator.last_update_success,
            "total_devices_count": len(devices),
            "controllable_switches_count": sum(
                1 for s in switches.values() if s is not None
            ),
            "controllable_buttons_count": sum(
                1 for b in buttons.values() if b is not None
            ),
        }

    # Export and loop safety diagnostics
    try:
        instance_id = await async_get_instance_id(hass)
        collection = collect_export_selection(hass, instance_id=instance_id)
        exclusion_counts: dict[str, int] = {}
        for exc in collection.exclusions:
            reason_str = str(exc.reason)
            exclusion_counts[reason_str] = exclusion_counts.get(reason_str, 0) + 1

        data["export_statistics"] = {
            "total_capabilities_count": len(collection.capabilities),
            "total_exclusions_count": len(collection.exclusions),
            "loop_exclusions_count": sum(
                1
                for exc in collection.exclusions
                if "domoticz" in str(exc.reason).lower()
                or "mirror" in str(exc.reason).lower()
            ),
            "exclusions_by_reason": exclusion_counts,
        }
    except ExportLabelNotFoundError:
        data["export_statistics"] = {
            "status": "export_label_not_found",
        }
    except Exception as err:
        data["export_statistics"] = {
            "error": type(err).__name__,
        }

    # Bridge manager sessions
    domain_data = hass.data.get(DOMAIN, {})
    manager = domain_data.get(DATA_BRIDGE_MANAGER)
    if manager is not None:
        data["bridge_statistics"] = {
            "active_sessions_count": len(manager._sessions),
            "configured_links_count": len(manager._links),
        }

    return data
