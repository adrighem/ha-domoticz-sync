"""Control request handling for the Home Assistant bridge."""

from __future__ import annotations

import json
import logging
from typing import Any

from homeassistant.helpers import entity_registry as er

from .bridge_types import BridgeSession
from .catalog_storage import (
    HomeAssistantBinaryCatalogStorage,
    HomeAssistantCatalogStorage,
)
from .const import CONTROLLABLE_EXPORT_DOMAINS
from .core import (
    Capability,
    CatalogStorageError,
    CompoundCapability,
    catalog_from_document,
)
from .core.protocol import (
    ControlResultStatus,
    ProtocolError,
    build_control_result,
)

_LOGGER = logging.getLogger(__name__)


def _parse_domoticz_color(color_str: str) -> dict[str, object] | None:
    """Parse Domoticz color into Home Assistant light service attributes."""
    if not color_str:
        return None
    raw = color_str.strip()
    if not raw:
        return None

    if raw.startswith("{") and raw.endswith("}"):
        try:
            payload = json.loads(raw)
            if isinstance(payload, dict):
                m = payload.get("m")
                t = payload.get("t")
                if isinstance(t, (int, float)) and t > 0 and m in (1, 2):
                    return {"color_temp": int(t)}

                r = payload.get("r")
                g = payload.get("g")
                b = payload.get("b")
                if (
                    isinstance(r, (int, float))
                    and isinstance(g, (int, float))
                    and isinstance(b, (int, float))
                ):
                    if (
                        r > 0
                        or g > 0
                        or b > 0
                        or m in (3, 4)
                        or not (isinstance(t, (int, float)) and t > 0)
                    ):
                        return {
                            "rgb_color": (
                                max(0, min(255, int(r))),
                                max(0, min(255, int(g))),
                                max(0, min(255, int(b))),
                            )
                        }
                if isinstance(t, (int, float)) and t > 0:
                    return {"color_temp": int(t)}
        except ValueError, TypeError:
            # Ignore malformed JSON or payload type errors and fall through.
            pass

    clean = raw.lstrip("#")
    if len(clean) == 6:
        try:
            return {
                "rgb_color": (
                    int(clean[0:2], 16),
                    int(clean[2:4], 16),
                    int(clean[4:6], 16),
                )
            }
        except ValueError:
            # Ignore invalid hex strings and fall through.
            pass

    return None


class DomoticzControlHandler:
    """Execution logic for control commands coming from Domoticz."""

    _application: Any

    async def _async_find_mapped_capability(
        self,
        entry_id: str,
        destination_id: str,
        target_id: str,
    ) -> Capability | CompoundCapability | None:
        """Find a mapped capability across numeric and binary catalogs."""
        if self._application is None:
            return None
        hass = self._application._hass

        # 1. Check numeric catalog
        num_storage = HomeAssistantCatalogStorage(
            hass,
            entry_id=entry_id,
            destination_id=destination_id,
        )
        try:
            num_doc = await num_storage.async_load()
            if num_doc is not None:
                num_catalog = catalog_from_document(num_doc)
                for record in num_catalog:
                    if record.target_id == target_id:
                        return record.capability
        except (
            CatalogStorageError,
            ProtocolError,
            ValueError,
            TypeError,
            KeyError,
        ):
            _LOGGER.warning(
                "Unable to load numeric export catalog for reverse command lookup"
            )

        # 2. Check binary catalog
        bin_storage = HomeAssistantBinaryCatalogStorage(
            hass,
            entry_id=entry_id,
            destination_id=destination_id,
        )
        try:
            bin_doc = await bin_storage.async_load()
            if bin_doc is not None:
                bin_catalog = catalog_from_document(bin_doc)
                for record in bin_catalog:
                    if record.target_id == target_id:
                        return record.capability
        except (
            CatalogStorageError,
            ProtocolError,
            ValueError,
            TypeError,
            KeyError,
        ):
            _LOGGER.warning(
                "Unable to load binary export catalog for reverse command lookup"
            )

        return None

    async def _async_handle_control_request(
        self,
        session: BridgeSession,
        request: Any,
    ) -> dict[str, object]:
        """Validate, map, and execute one incoming Domoticz control request."""
        if self._application is None:
            return build_control_result(
                session.selection,
                request.request_id,
                ControlResultStatus.REJECTED,
                error="bridge application is unavailable",
            )
        hass = self._application._hass

        if request.unit != 1:
            return build_control_result(
                session.selection,
                request.request_id,
                ControlResultStatus.REJECTED,
                error="target unit is not controllable",
            )

        capability = await self._async_find_mapped_capability(
            session.entry_id,
            session.destination_id,
            request.target_id,
        )
        if capability is None:
            return build_control_result(
                session.selection,
                request.request_id,
                ControlResultStatus.REJECTED,
                error="target is not owned by this session",
            )

        registry = er.async_get(hass)
        entry = registry.async_get(capability.source.object_id)
        if entry is None:
            return build_control_result(
                session.selection,
                request.request_id,
                ControlResultStatus.REJECTED,
                error="source entity is unavailable",
            )

        if entry.disabled_by is not None:
            return build_control_result(
                session.selection,
                request.request_id,
                ControlResultStatus.REJECTED,
                error="source entity is disabled",
            )

        entity_id = entry.entity_id
        if entry.domain not in CONTROLLABLE_EXPORT_DOMAINS:
            return build_control_result(
                session.selection,
                request.request_id,
                ControlResultStatus.REJECTED,
                error="source entity is not controllable",
            )

        current_state = hass.states.get(entity_id)
        if current_state is None or current_state.state == "unavailable":
            return build_control_result(
                session.selection,
                request.request_id,
                ControlResultStatus.REJECTED,
                error="source entity is unavailable",
            )

        cmd = request.command.lower()
        if entry.domain in {"switch", "input_boolean"}:
            if cmd == "on":
                domain = "homeassistant"
                service = "turn_on"
                data = {"entity_id": entity_id}
            elif cmd == "off":
                domain = "homeassistant"
                service = "turn_off"
                data = {"entity_id": entity_id}
            elif cmd == "toggle":
                domain = "homeassistant"
                service = "toggle"
                data = {"entity_id": entity_id}
            else:
                return build_control_result(
                    session.selection,
                    request.request_id,
                    ControlResultStatus.REJECTED,
                    error="command is not supported",
                )

        elif entry.domain == "light":
            if cmd == "on":
                domain = "light"
                service = "turn_on"
                data = {"entity_id": entity_id}
            elif cmd == "off":
                domain = "light"
                service = "turn_off"
                data = {"entity_id": entity_id}
            elif cmd == "toggle":
                domain = "light"
                service = "toggle"
                data = {"entity_id": entity_id}
            elif cmd in {"set level", "setlevel", "set_level"}:
                domain = "light"
                service = "turn_on"
                data = {
                    "entity_id": entity_id,
                    "brightness_pct": max(0, min(100, int(round(request.level)))),
                }
            elif cmd in {"set color", "setcolor", "set_color"}:
                domain = "light"
                service = "turn_on"
                data = {"entity_id": entity_id}
                if request.level > 0:
                    data["brightness_pct"] = max(0, min(100, int(round(request.level))))
                color_data = _parse_domoticz_color(request.color)
                if color_data is not None:
                    data.update(color_data)
            else:
                return build_control_result(
                    session.selection,
                    request.request_id,
                    ControlResultStatus.REJECTED,
                    error="command is not supported",
                )

        elif entry.domain == "cover":
            if cmd == "open":
                domain = "cover"
                service = "open_cover"
                data = {"entity_id": entity_id}
            elif cmd == "close":
                domain = "cover"
                service = "close_cover"
                data = {"entity_id": entity_id}
            elif cmd == "stop":
                domain = "cover"
                service = "stop_cover"
                data = {"entity_id": entity_id}
            elif cmd in {"set level", "setlevel", "set_level"}:
                domain = "cover"
                service = "set_cover_position"
                data = {
                    "entity_id": entity_id,
                    "position": max(0, min(100, int(round(request.level)))),
                }
            else:
                return build_control_result(
                    session.selection,
                    request.request_id,
                    ControlResultStatus.REJECTED,
                    error="command is not supported",
                )

        elif entry.domain == "button":
            if cmd in {"press", "on"}:
                domain = "button"
                service = "press"
                data = {"entity_id": entity_id}
            else:
                return build_control_result(
                    session.selection,
                    request.request_id,
                    ControlResultStatus.REJECTED,
                    error="command is not supported",
                )

        elif entry.domain == "vacuum":
            if cmd in {"on", "start", "clean"}:
                domain = "vacuum"
                service = "start"
                data = {"entity_id": entity_id}
            elif cmd in {"off", "dock", "return_to_base"}:
                domain = "vacuum"
                service = "return_to_base"
                data = {"entity_id": entity_id}
            elif cmd == "pause":
                domain = "vacuum"
                service = "pause"
                data = {"entity_id": entity_id}
            elif cmd == "stop":
                domain = "vacuum"
                service = "stop"
                data = {"entity_id": entity_id}
            elif cmd == "toggle":
                domain = "vacuum"
                if current_state.state in {"on", "cleaning"}:
                    service = "return_to_base"
                else:
                    service = "start"
                data = {"entity_id": entity_id}
            elif cmd in {"set level", "setlevel", "set_level"}:
                level_int = int(round(request.level))
                domain = "vacuum"
                if level_int == 10:
                    service = "start"
                elif level_int == 20:
                    service = "pause"
                elif level_int in {0, 30}:
                    service = "return_to_base"
                elif level_int == 40:
                    service = "stop"
                else:
                    return build_control_result(
                        session.selection,
                        request.request_id,
                        ControlResultStatus.REJECTED,
                        error="selector level is not supported",
                    )
                data = {"entity_id": entity_id}
        elif entry.domain in {"select", "input_select"}:
            domain = entry.domain
            service = "select_option"
            options = current_state.attributes.get("options", ())
            if not isinstance(options, (list, tuple)) or not options:
                return build_control_result(
                    session.selection,
                    request.request_id,
                    ControlResultStatus.REJECTED,
                    error="selector options are unavailable",
                )
            if cmd in {"set level", "setlevel", "set_level"}:
                level_int = int(round(request.level))
                idx = (level_int // 10) - 1
                if 0 <= idx < len(options):
                    selected_option = options[idx]
                elif 0 <= level_int // 10 < len(options) and level_int % 10 == 0:
                    selected_option = options[level_int // 10]
                else:
                    return build_control_result(
                        session.selection,
                        request.request_id,
                        ControlResultStatus.REJECTED,
                        error="selector level is not supported",
                    )
                data = {"entity_id": entity_id, "option": selected_option}
            elif cmd in {"select_option", "selectoption"}:
                selected_option = request.color or ""
                if not selected_option or selected_option not in options:
                    return build_control_result(
                        session.selection,
                        request.request_id,
                        ControlResultStatus.REJECTED,
                        error="option is not supported",
                    )
                data = {"entity_id": entity_id, "option": selected_option}
            else:
                return build_control_result(
                    session.selection,
                    request.request_id,
                    ControlResultStatus.REJECTED,
                    error="command is not supported",
                )
        else:
            return build_control_result(
                session.selection,
                request.request_id,
                ControlResultStatus.REJECTED,
                error="source entity is not controllable",
            )

        try:
            await hass.services.async_call(
                domain,
                service,
                data,
                blocking=True,
            )
        except Exception:
            return build_control_result(
                session.selection,
                request.request_id,
                ControlResultStatus.REJECTED,
                error="service call failed",
            )

        return build_control_result(
            session.selection,
            request.request_id,
            ControlResultStatus.CONFIRMED,
        )
