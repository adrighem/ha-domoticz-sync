"""Application wire message builders and parsers.

The module is deliberately host-neutral and uses only Python 3.9-compatible
standard-library features.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple

from ._handshake_messages import (
    _require_export_selection,
    _require_inventory_selection,
)
from ._serializers import (
    _build_export_apply,
    _build_export_apply_result,
    _ExportCodec,
    _inventory_result_to_dict,
    _inventory_target_from_dict,
    _normalize_inventory_payload,
    _normalize_payload,
    _parse_export_apply,
    _parse_export_apply_result,
)
from .capabilities import CapabilityKind, SourceIdentity
from .messages import (
    _CONTROL_REQUEST_KEYS,
    _CONTROL_RESULT_KEYS,
    _INVENTORY_REQUEST_KEYS,
    _INVENTORY_RESULT_KEYS,
    FEATURE_DOMOTICZ_CONTROL_V1,
    FEATURE_HA_EXPORT_BINARY_V1,
    FEATURE_HA_EXPORT_NUMERIC_V1,
    MAX_INVENTORY_PAGES,
    MAX_INVENTORY_TARGETS,
    MAX_INVENTORY_UNITS,
    ApplyRequest,
    ApplyResult,
    ApplyResultStatus,
    ControlRequest,
    ControlResult,
    ControlResultStatus,
    InventoryResult,
    InventoryResultStatus,
    InventoryTarget,
    ProtocolCompatibilityError,
    ProtocolFormatError,
    ProtocolSelection,
)
from .reconciliation import ReconciliationAction
from .validation import (
    _require_application_message,
    _require_string,
    _validate_request_id,
)

_NUMERIC_EXPORT_CODEC = _ExportCodec(
    feature=FEATURE_HA_EXPORT_NUMERIC_V1,
    capability_kinds=(CapabilityKind.NUMERIC, CapabilityKind.COMPOUND),
    request_type="apply",
    result_type="apply_result",
)
_BINARY_EXPORT_CODEC = _ExportCodec(
    feature=FEATURE_HA_EXPORT_BINARY_V1,
    capability_kinds=(CapabilityKind.BINARY, CapabilityKind.TEXT),
    request_type="binary_apply",
    result_type="binary_apply_result",
)


__all__ = [
    "assemble_inventory_results",
    "build_apply",
    "build_apply_result",
    "build_binary_apply",
    "build_binary_apply_result",
    "build_control",
    "build_control_color",
    "build_control_cover",
    "build_control_level",
    "build_control_result",
    "build_control_switch",
    "build_inventory_request",
    "build_inventory_result",
    "parse_apply",
    "parse_apply_result",
    "parse_binary_apply",
    "parse_binary_apply_result",
    "parse_control",
    "parse_control_result",
    "parse_inventory_request",
    "parse_inventory_result",
]


def build_inventory_request(
    selection: ProtocolSelection,
    request_id: str,
) -> Dict[str, object]:
    """Build one feature-gated request for a complete Domoticz inventory."""
    _require_inventory_selection(selection)
    _validate_request_id(request_id)
    return _normalize_inventory_payload(
        {
            "schema": 1,
            "type": "inventory_request",
            "request_id": request_id,
        }
    )


def parse_inventory_request(
    selection: ProtocolSelection,
    document: object,
) -> str:
    """Parse one exact inventory request and return its correlation ID."""
    _require_inventory_selection(selection)
    try:
        data = _require_application_message(
            _normalize_inventory_payload(document),
            _INVENTORY_REQUEST_KEYS,
            "inventory_request",
        )
        request_id = _require_string(data["request_id"])
        _validate_request_id(request_id)
        return request_id
    except (KeyError, TypeError, ValueError, OverflowError):
        raise ProtocolFormatError("invalid protocol message") from None


def build_inventory_result(
    selection: ProtocolSelection,
    result: InventoryResult,
) -> Dict[str, object]:
    """Build one strict, bounded page of a Domoticz inventory result."""
    _require_inventory_selection(selection)
    if not isinstance(result, InventoryResult):
        raise ProtocolFormatError("invalid protocol message")
    return _normalize_inventory_payload(_inventory_result_to_dict(result))


def parse_inventory_result(
    selection: ProtocolSelection,
    document: object,
) -> InventoryResult:
    """Parse one exact, bounded Domoticz inventory result page."""
    _require_inventory_selection(selection)
    try:
        data = _require_application_message(
            _normalize_inventory_payload(document),
            _INVENTORY_RESULT_KEYS,
            "inventory_result",
        )
        targets = data["targets"]
        if type(targets) is not list:
            raise ProtocolFormatError("invalid protocol message")
        return InventoryResult(
            request_id=_require_string(data["request_id"]),
            status=InventoryResultStatus(data["status"]),
            page=data["page"],
            complete=data["complete"],
            targets=tuple(_inventory_target_from_dict(target) for target in targets),
        )
    except (KeyError, TypeError, ValueError, OverflowError):
        raise ProtocolFormatError("invalid protocol message") from None


def assemble_inventory_results(
    selection: ProtocolSelection,
    request_id: str,
    pages: Iterable[InventoryResult],
) -> Tuple[InventoryTarget, ...]:
    """Validate and assemble one complete inventory without side effects."""
    validated_selection = _require_inventory_selection(selection)
    _validate_request_id(request_id)
    try:
        iterator = iter(pages)
    except TypeError:
        raise ProtocolFormatError("invalid protocol message") from None

    assembled: List[InventoryTarget] = []
    page_count = 0
    unit_count = 0
    terminal_seen = False
    previous_target_id: Optional[str] = None

    for result in iterator:
        page_count += 1
        if page_count > MAX_INVENTORY_PAGES:
            raise ProtocolFormatError("invalid protocol message")
        if not isinstance(result, InventoryResult):
            raise ProtocolFormatError("invalid protocol message")
        if (
            terminal_seen
            or result.request_id != request_id
            or result.page != page_count
        ):
            raise ProtocolFormatError("invalid protocol message")

        build_inventory_result(validated_selection, result)

        if result.status is InventoryResultStatus.REJECTED:
            raise ProtocolCompatibilityError("inventory rejected")

        for target in result.targets:
            if (
                previous_target_id is not None
                and target.target_id <= previous_target_id
            ):
                raise ProtocolFormatError("invalid protocol message")
            previous_target_id = target.target_id
            assembled.append(target)
            unit_count += len(target.units)
            if (
                len(assembled) > MAX_INVENTORY_TARGETS
                or unit_count > MAX_INVENTORY_UNITS
            ):
                raise ProtocolFormatError("invalid protocol message")

        terminal_seen = result.complete

    if page_count == 0 or not terminal_seen:
        raise ProtocolFormatError("invalid protocol message")
    return tuple(assembled)


def build_apply(
    selection: ProtocolSelection,
    request_id: str,
    action: ReconciliationAction,
) -> Dict[str, object]:
    """Build one strict Home Assistant-to-Domoticz application request."""
    return _build_export_apply(selection, request_id, action, _NUMERIC_EXPORT_CODEC)


def parse_apply(
    selection: ProtocolSelection,
    document: object,
) -> ApplyRequest:
    """Parse one exact application request into the neutral action model."""
    return _parse_export_apply(selection, document, _NUMERIC_EXPORT_CODEC)


def build_apply_result(
    selection: ProtocolSelection,
    request_id: str,
    status: ApplyResultStatus,
    target_id: Optional[str],
    source: Optional[SourceIdentity],
) -> Dict[str, object]:
    """Build one strict Domoticz-to-Home Assistant action result."""
    return _build_export_apply_result(
        selection,
        request_id,
        status,
        target_id,
        source,
        _NUMERIC_EXPORT_CODEC,
    )


def parse_apply_result(
    selection: ProtocolSelection,
    document: object,
) -> ApplyResult:
    """Parse one exact action result without accepting remote error details."""
    return _parse_export_apply_result(selection, document, _NUMERIC_EXPORT_CODEC)


def build_binary_apply(
    selection: ProtocolSelection,
    request_id: str,
    action: ReconciliationAction,
) -> Dict[str, object]:
    """Build one strict binary Home Assistant-to-Domoticz request."""
    return _build_export_apply(selection, request_id, action, _BINARY_EXPORT_CODEC)


def parse_binary_apply(
    selection: ProtocolSelection,
    document: object,
) -> ApplyRequest:
    """Parse one exact binary request into the neutral action model."""
    return _parse_export_apply(selection, document, _BINARY_EXPORT_CODEC)


def build_binary_apply_result(
    selection: ProtocolSelection,
    request_id: str,
    status: ApplyResultStatus,
    target_id: Optional[str],
    source: Optional[SourceIdentity],
) -> Dict[str, object]:
    """Build one strict binary Domoticz-to-Home Assistant action result."""
    return _build_export_apply_result(
        selection,
        request_id,
        status,
        target_id,
        source,
        _BINARY_EXPORT_CODEC,
    )


def parse_binary_apply_result(
    selection: ProtocolSelection,
    document: object,
) -> ApplyResult:
    """Parse one exact binary result without accepting remote error details."""
    return _parse_export_apply_result(selection, document, _BINARY_EXPORT_CODEC)


def build_control(
    selection: ProtocolSelection,
    request_id: str,
    target_id: str,
    unit: int = 1,
    command: str = "On",
    level: float = 0.0,
    color: str = "",
) -> Dict[str, object]:
    """Build one signed control request."""
    _require_export_selection(selection, FEATURE_DOMOTICZ_CONTROL_V1)
    request = ControlRequest(
        request_id=request_id,
        target_id=target_id,
        unit=unit,
        command=command,
        level=level,
        color=color,
    )
    return _normalize_payload(
        {
            "schema": 1,
            "type": "control_request",
            "request_id": request.request_id,
            "target_id": request.target_id,
            "unit": request.unit,
            "command": request.command,
            "level": request.level,
            "color": request.color,
        }
    )


def build_control_switch(
    selection: ProtocolSelection,
    request_id: str,
    target_id: str,
    on: bool,
    unit: int = 1,
) -> Dict[str, object]:
    """Build one switch control request (On or Off)."""
    return build_control(
        selection=selection,
        request_id=request_id,
        target_id=target_id,
        unit=unit,
        command="On" if on else "Off",
    )


def build_control_level(
    selection: ProtocolSelection,
    request_id: str,
    target_id: str,
    level: float,
    unit: int = 1,
) -> Dict[str, object]:
    """Build one level / brightness / position control request."""
    return build_control(
        selection=selection,
        request_id=request_id,
        target_id=target_id,
        unit=unit,
        command="Set Level",
        level=level,
    )


def build_control_color(
    selection: ProtocolSelection,
    request_id: str,
    target_id: str,
    color: str,
    level: float = 100.0,
    unit: int = 1,
) -> Dict[str, object]:
    """Build one color control request."""
    return build_control(
        selection=selection,
        request_id=request_id,
        target_id=target_id,
        unit=unit,
        command="Set Color",
        level=level,
        color=color,
    )


def build_control_cover(
    selection: ProtocolSelection,
    request_id: str,
    target_id: str,
    action: str,
    level: float = 0.0,
    unit: int = 1,
) -> Dict[str, object]:
    """Build one cover action request (Open, Close, Stop, etc.)."""
    return build_control(
        selection=selection,
        request_id=request_id,
        target_id=target_id,
        unit=unit,
        command=action,
        level=level,
    )


def parse_control(
    selection: ProtocolSelection,
    document: object,
) -> ControlRequest:
    """Parse one control request."""
    _require_export_selection(selection, FEATURE_DOMOTICZ_CONTROL_V1)
    try:
        data = _require_application_message(
            _normalize_payload(document),
            _CONTROL_REQUEST_KEYS,
            "control_request",
        )
        return ControlRequest(
            request_id=_require_string(data["request_id"]),
            target_id=_require_string(data["target_id"]),
            unit=data["unit"],
            command=_require_string(data["command"]),
            level=data["level"],
            color=_require_string(data["color"]),
        )
    except (KeyError, TypeError, ValueError, OverflowError):
        raise ProtocolFormatError("invalid protocol message") from None


def build_control_result(
    selection: ProtocolSelection,
    request_id: str,
    status: ControlResultStatus,
    error: Optional[str] = None,
) -> Dict[str, object]:
    """Build one signed control result."""
    _require_export_selection(selection, FEATURE_DOMOTICZ_CONTROL_V1)
    result = ControlResult(request_id=request_id, status=status, error=error)
    return _normalize_payload(
        {
            "schema": 1,
            "type": "control_result",
            "request_id": result.request_id,
            "status": result.status.value,
            "error": result.error,
        }
    )


def parse_control_result(
    selection: ProtocolSelection,
    document: object,
) -> ControlResult:
    """Parse one control result."""
    _require_export_selection(selection, FEATURE_DOMOTICZ_CONTROL_V1)
    try:
        data = _require_application_message(
            _normalize_payload(document),
            _CONTROL_RESULT_KEYS,
            "control_result",
        )
        return ControlResult(
            request_id=_require_string(data["request_id"]),
            status=ControlResultStatus(data["status"]),
            error=data["error"]
            if data["error"] is None
            else _require_string(data["error"]),
        )
    except (KeyError, TypeError, ValueError, OverflowError):
        raise ProtocolFormatError("invalid protocol message") from None
