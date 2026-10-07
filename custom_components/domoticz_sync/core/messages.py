"""Error types, enums, dataclasses, and message schemas for wire protocol.

The module is deliberately host-neutral and uses only Python 3.9-compatible
standard-library features.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple

from ._constants import (
    _ACTION_KEYS,
    _APPLICATION_READY_KEYS,
    _APPLY_KEYS,
    _APPLY_RESULT_KEYS,
    _AUTHENTICATE_KEYS,
    _CAPABILITY_KEYS,
    _CHALLENGE_KEYS,
    _COMPOUND_CAPABILITY_KEYS,
    _CONTROL_REQUEST_KEYS,
    _CONTROL_RESULT_KEYS,
    _ENVELOPE_KEYS,
    _HELLO_KEYS,
    _INVENTORY_REQUEST_KEYS,
    _INVENTORY_RESULT_KEYS,
    _INVENTORY_TARGET_KEYS,
    _INVENTORY_UNIT_KEYS,
    _READY_KEYS,
    _SOURCE_KEYS,
    _V2_CHALLENGE_KEYS,
    _V2_HELLO_KEYS,
    DIRECTION_DOMOTICZ_TO_HA,
    DIRECTION_HA_TO_DOMOTICZ,
    FEATURE_DOMOTICZ_CONTROL_V1,
    FEATURE_DOMOTICZ_INVENTORY_V1,
    FEATURE_HA_EXPORT_BINARY_V1,
    FEATURE_HA_EXPORT_CONTINUOUS_V1,
    FEATURE_HA_EXPORT_NUMERIC_V1,
    INVENTORY_TIMEOUT_SECONDS,
    MAX_FEATURE_IDS,
    MAX_INVENTORY_NAME_BYTES,
    MAX_INVENTORY_OPTION_BYTES,
    MAX_INVENTORY_PAGES,
    MAX_INVENTORY_PAYLOAD_BYTES,
    MAX_INVENTORY_S_VALUE_BYTES,
    MAX_INVENTORY_TARGET_ID_BYTES,
    MAX_INVENTORY_TARGETS,
    MAX_INVENTORY_TARGETS_PER_PAGE,
    MAX_INVENTORY_UNITS,
    MAX_JSON_DEPTH,
    MAX_MESSAGE_BYTES,
    MAX_PROTOCOL_TOKENS,
    MAX_SAFE_INTEGER,
    MAX_SEQUENCE,
    NONCE_BITS,
    PAIRING_KEY_BITS,
    PROTOCOL_VERSION,
    PROTOCOL_VERSION_V1,
    PROTOCOL_VERSION_V2,
    SUPPORTED_V2_FEATURES,
    SUPPORTED_WEBSOCKET_SUBPROTOCOLS,
    WEBSOCKET_SUBPROTOCOL_V2,
)
from ._handshake_messages import (
    ClientHello,
    HandshakeContext,
    ProtocolSelection,
    V2ClientHello,
    V2HandshakeContext,
)
from .capabilities import CapabilityKind, SourceIdentity
from .reconciliation import ReconciliationAction


class ProtocolError(ValueError):
    """Base class for safe protocol failures."""


class ProtocolFormatError(ProtocolError):
    """A protocol document or value does not match its selected format."""


class ProtocolAuthenticationError(ProtocolError):
    """A proof, signature, or authenticated session value is invalid."""


class ProtocolSequenceError(ProtocolError):
    """An authenticated envelope is replayed, missing, or out of order."""


class ProtocolCompatibilityError(ProtocolError):
    """The peers have no mutually supported authenticated behavior."""


class ApplyResultStatus(str, Enum):
    """The only safe outcomes returned for one remote action."""

    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class InventoryResultStatus(str, Enum):
    """The only safe outcomes for one authenticated inventory request."""

    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class ControlResultStatus(str, Enum):
    """The only safe outcomes returned for one remote control action."""

    CONFIRMED = "confirmed"
    REJECTED = "rejected"


@dataclass(frozen=True)
class _ExportCodec:
    """One feature-gated application message family for a capability kind."""

    feature: str
    capability_kinds: Tuple[CapabilityKind, ...]
    request_type: str
    result_type: str


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

from .validation import (  # noqa: E402
    _validate_bounded_integer,
    _validate_inventory_string,
    _validate_inventory_target_id,
    _validate_request_id,
    _validate_strict_bool,
    _validate_target_id,
)


@dataclass(frozen=True)
class VerifiedEnvelope:
    """One authenticated, in-order application payload."""

    session_id: str
    direction: str
    sequence: int
    payload: Dict[str, object]


@dataclass(frozen=True)
class ApplyRequest:
    """One correlation identifier and complete target-neutral action."""

    request_id: str
    action: ReconciliationAction

    def __post_init__(self) -> None:
        """Validate direct construction as strictly as parsed input."""
        _validate_request_id(self.request_id)
        if not isinstance(self.action, ReconciliationAction):
            raise ProtocolFormatError("invalid protocol message")


@dataclass(frozen=True)
class ApplyResult:
    """A sanitized remote confirmation or rejection."""

    request_id: str
    status: ApplyResultStatus
    target_id: Optional[str]
    source: Optional[SourceIdentity]

    def __post_init__(self) -> None:
        """Require result fields to agree with their status."""
        _validate_request_id(self.request_id)
        if not isinstance(self.status, ApplyResultStatus):
            raise ProtocolFormatError("invalid protocol message")
        if self.status is ApplyResultStatus.CONFIRMED:
            _validate_target_id(self.target_id)
            if not isinstance(self.source, SourceIdentity):
                raise ProtocolFormatError("invalid protocol message")
        elif self.target_id is not None or self.source is not None:
            raise ProtocolFormatError("invalid protocol message")


@dataclass(frozen=True)
class ControlRequest:
    """One correlation identifier and complete target-neutral control action."""

    request_id: str
    target_id: str
    unit: int
    command: str
    level: float
    color: str

    def __post_init__(self) -> None:
        """Validate direct construction as strictly as parsed input."""
        _validate_request_id(self.request_id)
        _validate_target_id(self.target_id)
        _validate_bounded_integer(self.unit, 1, 255)
        if not isinstance(self.command, str):
            raise TypeError("command must be a string")
        if not self.command.strip():
            raise ValueError("command must not be empty")
        if type(self.level) not in (int, float) or not math.isfinite(self.level):
            raise TypeError("level must be a finite number")
        if not isinstance(self.color, str):
            raise TypeError("color must be a string")


@dataclass(frozen=True)
class ControlResult:
    """A sanitized control confirmation or rejection."""

    request_id: str
    status: ControlResultStatus
    error: Optional[str] = None

    def __post_init__(self) -> None:
        """Require result fields to agree with their status."""
        _validate_request_id(self.request_id)
        if not isinstance(self.status, ControlResultStatus):
            raise TypeError("status must be a ControlResultStatus")
        if self.status is ControlResultStatus.CONFIRMED:
            if self.error is not None:
                raise ValueError("confirmed control results must not have an error")
        else:
            if self.error is not None:
                if not isinstance(self.error, str) or not self.error.strip():
                    raise ValueError(
                        "rejected control results require a non-empty string error"
                    )


@dataclass(frozen=True)
class InventoryUnit:
    """One bounded Domoticz unit observation inside an inventory snapshot."""

    unit: int
    name: str
    type: int
    subtype: int
    switch_type: int
    used: bool
    n_value: int
    s_value: str
    custom_option: Optional[str]
    has_other_options: bool

    def __post_init__(self) -> None:
        """Validate direct construction as strictly as parsed input."""
        _validate_bounded_integer(self.unit, 1, 255)
        _validate_inventory_string(self.name, MAX_INVENTORY_NAME_BYTES)
        _validate_bounded_integer(self.type, 0, MAX_SAFE_INTEGER)
        _validate_bounded_integer(self.subtype, 0, MAX_SAFE_INTEGER)
        _validate_bounded_integer(self.switch_type, 0, MAX_SAFE_INTEGER)
        _validate_strict_bool(self.used)
        _validate_bounded_integer(
            self.n_value,
            -MAX_SAFE_INTEGER,
            MAX_SAFE_INTEGER,
        )
        _validate_inventory_string(self.s_value, MAX_INVENTORY_S_VALUE_BYTES)
        if self.custom_option is not None:
            _validate_inventory_string(
                self.custom_option,
                MAX_INVENTORY_OPTION_BYTES,
            )
        _validate_strict_bool(self.has_other_options)


@dataclass(frozen=True)
class InventoryTarget:
    """One hardware-scoped Domoticz parent and its ordered units."""

    target_id: str
    timed_out: bool
    units: Tuple[InventoryUnit, ...]

    def __post_init__(self) -> None:
        """Require a deterministic, duplicate-free unit ordering."""
        _validate_inventory_target_id(self.target_id)
        _validate_strict_bool(self.timed_out)
        if type(self.units) is not tuple or len(self.units) > MAX_INVENTORY_UNITS:
            raise ProtocolFormatError("invalid protocol message")
        unit_numbers: List[int] = []
        for unit in self.units:
            if not isinstance(unit, InventoryUnit):
                raise ProtocolFormatError("invalid protocol message")
            unit_numbers.append(unit.unit)
        if unit_numbers != sorted(unit_numbers) or len(unit_numbers) != len(
            set(unit_numbers)
        ):
            raise ProtocolFormatError("invalid protocol message")


@dataclass(frozen=True)
class InventoryResult:
    """One page of an authenticated, bounded Domoticz inventory snapshot."""

    request_id: str
    status: InventoryResultStatus
    page: int
    complete: bool
    targets: Tuple[InventoryTarget, ...]

    def __post_init__(self) -> None:
        """Require one exact confirmed page or sanitized rejection."""
        _validate_request_id(self.request_id)
        if not isinstance(self.status, InventoryResultStatus):
            raise ProtocolFormatError("invalid protocol message")
        _validate_bounded_integer(self.page, 1, MAX_INVENTORY_PAGES)
        _validate_strict_bool(self.complete)
        if (
            type(self.targets) is not tuple
            or len(self.targets) > MAX_INVENTORY_TARGETS_PER_PAGE
        ):
            raise ProtocolFormatError("invalid protocol message")

        target_ids: List[str] = []
        for target in self.targets:
            if not isinstance(target, InventoryTarget):
                raise ProtocolFormatError("invalid protocol message")
            target_ids.append(target.target_id)
        if target_ids != sorted(target_ids) or len(target_ids) != len(set(target_ids)):
            raise ProtocolFormatError("invalid protocol message")

        if self.status is InventoryResultStatus.REJECTED:
            if self.page != 1 or not self.complete or self.targets:
                raise ProtocolFormatError("invalid protocol message")
        elif not self.targets and (self.page != 1 or not self.complete):
            raise ProtocolFormatError("invalid protocol message")
        elif self.page == MAX_INVENTORY_PAGES and not self.complete:
            raise ProtocolFormatError("invalid protocol message")


__all__ = [
    "ApplyRequest",
    "ApplyResult",
    "ApplyResultStatus",
    "ClientHello",
    "ControlRequest",
    "ControlResult",
    "ControlResultStatus",
    "DIRECTION_DOMOTICZ_TO_HA",
    "DIRECTION_HA_TO_DOMOTICZ",
    "FEATURE_DOMOTICZ_CONTROL_V1",
    "FEATURE_DOMOTICZ_INVENTORY_V1",
    "FEATURE_HA_EXPORT_BINARY_V1",
    "FEATURE_HA_EXPORT_CONTINUOUS_V1",
    "FEATURE_HA_EXPORT_NUMERIC_V1",
    "HandshakeContext",
    "INVENTORY_TIMEOUT_SECONDS",
    "InventoryResult",
    "InventoryResultStatus",
    "InventoryTarget",
    "InventoryUnit",
    "MAX_FEATURE_IDS",
    "MAX_INVENTORY_NAME_BYTES",
    "MAX_INVENTORY_OPTION_BYTES",
    "MAX_INVENTORY_PAGES",
    "MAX_INVENTORY_PAYLOAD_BYTES",
    "MAX_INVENTORY_S_VALUE_BYTES",
    "MAX_INVENTORY_TARGET_ID_BYTES",
    "MAX_INVENTORY_TARGETS",
    "MAX_INVENTORY_TARGETS_PER_PAGE",
    "MAX_INVENTORY_UNITS",
    "MAX_JSON_DEPTH",
    "MAX_MESSAGE_BYTES",
    "MAX_PROTOCOL_TOKENS",
    "MAX_SAFE_INTEGER",
    "MAX_SEQUENCE",
    "NONCE_BITS",
    "PAIRING_KEY_BITS",
    "PROTOCOL_VERSION",
    "PROTOCOL_VERSION_V1",
    "PROTOCOL_VERSION_V2",
    "ProtocolAuthenticationError",
    "ProtocolCompatibilityError",
    "ProtocolError",
    "ProtocolFormatError",
    "ProtocolSelection",
    "ProtocolSequenceError",
    "SUPPORTED_V2_FEATURES",
    "SUPPORTED_WEBSOCKET_SUBPROTOCOLS",
    "V2ClientHello",
    "V2HandshakeContext",
    "VerifiedEnvelope",
    "WEBSOCKET_SUBPROTOCOL_V2",
    "_ACTION_KEYS",
    "_APPLICATION_READY_KEYS",
    "_APPLY_KEYS",
    "_APPLY_RESULT_KEYS",
    "_AUTHENTICATE_KEYS",
    "_CAPABILITY_KEYS",
    "_CHALLENGE_KEYS",
    "_COMPOUND_CAPABILITY_KEYS",
    "_CONTROL_REQUEST_KEYS",
    "_CONTROL_RESULT_KEYS",
    "_ENVELOPE_KEYS",
    "_HELLO_KEYS",
    "_INVENTORY_REQUEST_KEYS",
    "_INVENTORY_RESULT_KEYS",
    "_INVENTORY_TARGET_KEYS",
    "_INVENTORY_UNIT_KEYS",
    "_READY_KEYS",
    "_SOURCE_KEYS",
    "_V2_CHALLENGE_KEYS",
    "_V2_HELLO_KEYS",
]
