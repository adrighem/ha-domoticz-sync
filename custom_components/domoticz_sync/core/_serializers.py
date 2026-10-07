"""Internal dict serialization helpers for protocol objects."""

from __future__ import annotations

from typing import Dict, Union

from .capabilities import (
    Availability,
    Capability,
    CapabilityKind,
    CompoundCapability,
    SourceIdentity,
)
from .codec import canonical_json_bytes, canonical_json_dumps, canonical_json_loads
from .messages import (
    _ACTION_KEYS,
    _APPLY_KEYS,
    _APPLY_RESULT_KEYS,
    _CAPABILITY_KEYS,
    _COMPOUND_CAPABILITY_KEYS,
    _INVENTORY_TARGET_KEYS,
    _INVENTORY_UNIT_KEYS,
    _SOURCE_KEYS,
    MAX_INVENTORY_PAYLOAD_BYTES,
    ApplyRequest,
    ApplyResult,
    ApplyResultStatus,
    InventoryResult,
    InventoryTarget,
    InventoryUnit,
    ProtocolFormatError,
    ProtocolSelection,
    _ExportCodec,
)
from .reconciliation import ReconciliationAction, ReconciliationActionKind
from .validation import (
    _require_application_message,
    _require_exact_object,
    _require_export_selection,
    _require_string,
)

__all__ = [
    "_action_from_dict",
    "_action_to_dict",
    "_build_export_apply",
    "_build_export_apply_result",
    "_capability_from_dict",
    "_capability_to_dict",
    "_inventory_result_to_dict",
    "_inventory_target_from_dict",
    "_inventory_target_to_dict",
    "_inventory_unit_from_dict",
    "_inventory_unit_to_dict",
    "_normalize_inventory_payload",
    "_normalize_payload",
    "_parse_export_apply",
    "_parse_export_apply_result",
    "_source_from_dict",
    "_source_to_dict",
]


def _normalize_payload(payload: object) -> Dict[str, object]:
    """Validate and defensively copy one JSON object payload."""
    if type(payload) is not dict:
        raise ProtocolFormatError("invalid protocol message")
    normalized = canonical_json_loads(canonical_json_dumps(payload))
    if type(normalized) is not dict:
        raise ProtocolFormatError("invalid protocol message")
    return normalized


def _normalize_inventory_payload(payload: object) -> Dict[str, object]:
    """Normalize one inventory payload inside its reserved envelope budget."""
    normalized = _normalize_payload(payload)
    if len(canonical_json_bytes(normalized)) > MAX_INVENTORY_PAYLOAD_BYTES:
        raise ProtocolFormatError("invalid protocol message")
    return normalized


def _inventory_unit_to_dict(unit: InventoryUnit) -> Dict[str, object]:
    """Serialize one complete, bounded inventory unit."""
    return {
        "unit": unit.unit,
        "name": unit.name,
        "type": unit.type,
        "subtype": unit.subtype,
        "switch_type": unit.switch_type,
        "used": unit.used,
        "n_value": unit.n_value,
        "s_value": unit.s_value,
        "custom_option": unit.custom_option,
        "has_other_options": unit.has_other_options,
    }


def _inventory_unit_from_dict(document: object) -> InventoryUnit:
    """Parse one exact inventory unit using strict scalar types."""
    _require_exact_object(document, _INVENTORY_UNIT_KEYS)
    return InventoryUnit(
        unit=document["unit"],
        name=document["name"],
        type=document["type"],
        subtype=document["subtype"],
        switch_type=document["switch_type"],
        used=document["used"],
        n_value=document["n_value"],
        s_value=document["s_value"],
        custom_option=document["custom_option"],
        has_other_options=document["has_other_options"],
    )


def _inventory_target_to_dict(target: InventoryTarget) -> Dict[str, object]:
    """Serialize one parent target and all of its ordered units."""
    return {
        "target_id": target.target_id,
        "timed_out": target.timed_out,
        "units": [_inventory_unit_to_dict(unit) for unit in target.units],
    }


def _inventory_target_from_dict(document: object) -> InventoryTarget:
    """Parse one exact parent target without dropping empty containers."""
    _require_exact_object(document, _INVENTORY_TARGET_KEYS)
    units = document["units"]
    if type(units) is not list:
        raise ProtocolFormatError("invalid protocol message")
    return InventoryTarget(
        target_id=document["target_id"],
        timed_out=document["timed_out"],
        units=tuple(_inventory_unit_from_dict(unit) for unit in units),
    )


def _inventory_result_to_dict(result: InventoryResult) -> Dict[str, object]:
    """Serialize one exact inventory result page."""
    return {
        "schema": 1,
        "type": "inventory_result",
        "request_id": result.request_id,
        "status": result.status.value,
        "page": result.page,
        "complete": result.complete,
        "targets": [_inventory_target_to_dict(target) for target in result.targets],
    }


def _source_to_dict(source: SourceIdentity) -> Dict[str, object]:
    """Serialize one complete source identity."""
    return {
        "system": source.system,
        "instance_id": source.instance_id,
        "object_id": source.object_id,
        "capability_id": source.capability_id,
    }


def _source_from_dict(document: object) -> SourceIdentity:
    """Parse one exact source identity using its neutral model rules."""
    _require_exact_object(document, _SOURCE_KEYS)
    return SourceIdentity(
        system=document["system"],
        instance_id=document["instance_id"],
        object_id=document["object_id"],
        capability_id=document["capability_id"],
    )


def _capability_to_dict(
    capability: Union[Capability, CompoundCapability],
) -> Dict[str, object]:
    """Serialize every field that defines one capability snapshot."""
    if isinstance(capability, CompoundCapability):
        return {
            "source": _source_to_dict(capability.source),
            "kind": capability.kind.value,
            "name": capability.name,
            "availability": capability.availability.value,
            "capabilities": [
                _capability_to_dict(cap) for cap in capability.capabilities
            ],
        }
    return {
        "source": _source_to_dict(capability.source),
        "kind": capability.kind.value,
        "name": capability.name,
        "value": capability.value,
        "availability": capability.availability.value,
        "semantic": capability.semantic,
        "unit": capability.unit,
        "state_class": capability.state_class,
        "options": list(capability.options) if capability.options is not None else None,
    }


def _capability_from_dict(document: object) -> Union[Capability, CompoundCapability]:
    """Parse one exact capability using the complete neutral semantics."""
    if not isinstance(document, dict):
        raise TypeError("capability must be a dict")
    kind_str = document.get("kind")
    if kind_str == CapabilityKind.COMPOUND.value:
        _require_exact_object(document, _COMPOUND_CAPABILITY_KEYS)
        source = _source_from_dict(document["source"])
        nested_list = document["capabilities"]
        if not isinstance(nested_list, list):
            raise TypeError("capabilities must be a list")
        capabilities = tuple(_capability_from_dict(item) for item in nested_list)
        for cap in capabilities:
            if not isinstance(cap, Capability):
                raise TypeError(
                    "compound capability nested list must contain Capability values"
                )
        return CompoundCapability(
            source=source,
            name=document["name"],
            capabilities=capabilities,
            availability=Availability(document["availability"]),
        )

    _require_exact_object(document, _CAPABILITY_KEYS)
    raw_options = document["options"]
    if raw_options is not None:
        if not isinstance(raw_options, list):
            raise TypeError("options must be a list or None")
        options = tuple(raw_options)
    else:
        options = None

    return Capability(
        source=_source_from_dict(document["source"]),
        kind=CapabilityKind(document["kind"]),
        name=document["name"],
        value=document["value"],
        availability=Availability(document["availability"]),
        semantic=document["semantic"],
        unit=document["unit"],
        state_class=document["state_class"],
        options=options,
    )


def _action_to_dict(action: ReconciliationAction) -> Dict[str, object]:
    """Serialize every field that defines one reconciliation action."""
    return {
        "kind": action.kind.value,
        "capability": _capability_to_dict(action.capability),
        "target_id": action.target_id,
        "stale": action.stale,
    }


def _action_from_dict(document: object) -> ReconciliationAction:
    """Parse one exact action using the complete neutral model semantics."""
    _require_exact_object(document, _ACTION_KEYS)
    return ReconciliationAction(
        kind=ReconciliationActionKind(document["kind"]),
        capability=_capability_from_dict(document["capability"]),
        target_id=document["target_id"],
        stale=document["stale"],
    )


def _build_export_apply(
    selection: ProtocolSelection,
    request_id: str,
    action: ReconciliationAction,
    codec: _ExportCodec,
) -> Dict[str, object]:
    """Build one feature-gated export request with an exact discriminator."""
    _require_export_selection(selection, codec.feature)
    request = ApplyRequest(request_id=request_id, action=action)
    if request.action.capability.kind not in codec.capability_kinds:
        raise ProtocolFormatError("invalid protocol message")
    return _normalize_payload(
        {
            "schema": 1,
            "type": codec.request_type,
            "request_id": request.request_id,
            "action": _action_to_dict(request.action),
        }
    )


def _parse_export_apply(
    selection: ProtocolSelection,
    document: object,
    codec: _ExportCodec,
) -> ApplyRequest:
    """Parse one feature-gated export request into the neutral action model."""
    _require_export_selection(selection, codec.feature)
    try:
        data = _require_application_message(
            _normalize_payload(document),
            _APPLY_KEYS,
            codec.request_type,
        )
        request = ApplyRequest(
            request_id=_require_string(data["request_id"]),
            action=_action_from_dict(data["action"]),
        )
        if request.action.capability.kind not in codec.capability_kinds:
            raise ProtocolFormatError("invalid protocol message")
        return request
    except (KeyError, TypeError, ValueError, OverflowError):
        raise ProtocolFormatError("invalid protocol message") from None


def _build_export_apply_result(
    selection: ProtocolSelection,
    request_id: str,
    status: ApplyResultStatus,
    target_id: Union[str, None],
    source: Union[SourceIdentity, None],
    codec: _ExportCodec,
) -> Dict[str, object]:
    """Build one feature-gated export result without remote error details."""
    _require_export_selection(selection, codec.feature)
    result = ApplyResult(
        request_id=request_id,
        status=status,
        target_id=target_id,
        source=source,
    )
    return _normalize_payload(
        {
            "schema": 1,
            "type": codec.result_type,
            "request_id": result.request_id,
            "status": result.status.value,
            "target_id": result.target_id,
            "source": (
                _source_to_dict(result.source) if result.source is not None else None
            ),
        }
    )


def _parse_export_apply_result(
    selection: ProtocolSelection,
    document: object,
    codec: _ExportCodec,
) -> ApplyResult:
    """Parse one feature-gated export result without accepting error details."""
    _require_export_selection(selection, codec.feature)
    try:
        data = _require_application_message(
            _normalize_payload(document),
            _APPLY_RESULT_KEYS,
            codec.result_type,
        )
        source_data = data["source"]
        return ApplyResult(
            request_id=_require_string(data["request_id"]),
            status=ApplyResultStatus(data["status"]),
            target_id=data["target_id"],
            source=(
                _source_from_dict(source_data) if source_data is not None else None
            ),
        )
    except (KeyError, TypeError, ValueError, OverflowError):
        raise ProtocolFormatError("invalid protocol message") from None
