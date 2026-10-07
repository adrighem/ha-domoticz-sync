"""Validation helpers and invariants for protocol objects and messages.

The module is deliberately host-neutral and uses only Python 3.9-compatible
standard-library features.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence, Tuple

from ._constants import (
    MAX_FEATURE_IDS,
    MAX_INVENTORY_TARGET_ID_BYTES,
    MAX_PROTOCOL_TOKENS,
    MAX_SEQUENCE,
    PROTOCOL_VERSION,
)
from ._crypto_tokens import _SECRET_BYTES, _TOKEN_RE, generate_nonce
from .errors import ProtocolFormatError

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_WEBSOCKET_TOKEN_RE = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]{1,128}$")
_DIRECTIONS = {
    "domoticz_to_home_assistant",
    "home_assistant_to_domoticz",
}


def generate_link_id() -> str:
    """Generate a link ID accepted by the identifier schema."""
    return "link_" + generate_nonce()


def generate_destination_id() -> str:
    """Generate a destination ID accepted by the identifier schema."""
    return "domoticz_" + generate_nonce()


def validate_pairing_key(pairing_key: str) -> None:
    """Validate a pairing key string invariant."""
    if type(pairing_key) is not str or _TOKEN_RE.fullmatch(pairing_key) is None:
        raise ProtocolFormatError("invalid protocol message")


def validate_link_id(link_id: str) -> None:
    """Validate a link ID identifier invariant."""
    if type(link_id) is not str or _IDENTIFIER_RE.fullmatch(link_id) is None:
        raise ProtocolFormatError("invalid protocol message")


def validate_destination_id(destination_id: str) -> None:
    """Validate a destination ID identifier invariant."""
    if (
        type(destination_id) is not str
        or _IDENTIFIER_RE.fullmatch(destination_id) is None
    ):
        raise ProtocolFormatError("invalid protocol message")


def validate_nonce(nonce: str) -> None:
    """Validate a handshake nonce invariant."""
    if type(nonce) is not str or _TOKEN_RE.fullmatch(nonce) is None:
        raise ProtocolFormatError("invalid protocol message")


def validate_protocol_tokens(protocols: Sequence[str]) -> Tuple[str, ...]:
    """Validate a non-empty list of WebSocket subprotocol candidates."""
    if type(protocols) not in (list, tuple) or not protocols:
        raise ProtocolFormatError("invalid protocol message")
    if len(protocols) > MAX_PROTOCOL_TOKENS:
        raise ProtocolFormatError("invalid protocol message")

    validated: List[str] = []
    for item in protocols:
        if (
            type(item) is not str
            or _WEBSOCKET_TOKEN_RE.fullmatch(item) is None
            or item in validated
        ):
            raise ProtocolFormatError("invalid protocol message")
        validated.append(item)
    return tuple(validated)


def validate_feature_ids(features: Sequence[str]) -> Tuple[str, ...]:
    """Validate and sort optional feature identifiers."""
    if type(features) not in (list, tuple):
        raise ProtocolFormatError("invalid protocol message")
    if len(features) > MAX_FEATURE_IDS:
        raise ProtocolFormatError("invalid protocol message")

    validated: List[str] = []
    for item in features:
        if type(item) is not str or item in validated:
            raise ProtocolFormatError("invalid protocol message")
        _validate_feature_id(item)
        validated.append(item)
    res = tuple(validated)
    if res != tuple(sorted(res)):
        raise ProtocolFormatError("invalid protocol message")
    return res


def select_websocket_subprotocol(
    client_protocols: Sequence[str],
    server_protocols: Sequence[str],
) -> Optional[str]:
    """Find the first subprotocol offered by client that server supports."""
    validated_client = validate_protocol_tokens(client_protocols)
    validated_server = validate_protocol_tokens(server_protocols)
    for protocol in validated_client:
        if protocol in validated_server:
            return protocol
    return None


def negotiate_features(
    client_features: Sequence[str],
    server_features: Sequence[str],
) -> Tuple[str, ...]:
    """Intersect sorted feature IDs offered by client and supported by server."""
    validated_client = validate_feature_ids(client_features)
    validated_server = validate_feature_ids(server_features)
    intersected = [f for f in validated_client if f in validated_server]
    return tuple(sorted(intersected))


def _validate_feature_id(feature: str) -> None:
    """Require one lowercase identifier for optional feature flags."""
    if type(feature) is not str or _WEBSOCKET_TOKEN_RE.fullmatch(feature) is None:
        raise ProtocolFormatError("invalid protocol message")


def _validate_request_id(request_id: str) -> None:
    """Require a valid correlation request ID."""
    if type(request_id) is not str or _IDENTIFIER_RE.fullmatch(request_id) is None:
        raise ProtocolFormatError("invalid protocol message")


def _validate_target_id(target_id: str) -> None:
    """Require a valid hardware target ID."""
    if type(target_id) is not str or _IDENTIFIER_RE.fullmatch(target_id) is None:
        raise ProtocolFormatError("invalid protocol message")


def _validate_inventory_target_id(target_id: str) -> None:
    """Validate a hardware-scoped Domoticz target identifier."""
    if (
        type(target_id) is not str
        or _IDENTIFIER_RE.fullmatch(target_id) is None
        or len(target_id.encode("utf-8")) > MAX_INVENTORY_TARGET_ID_BYTES
    ):
        raise ProtocolFormatError("invalid protocol message")


def _validate_inventory_string(value: str, max_bytes: int) -> None:
    """Validate a string inside an inventory payload."""
    if type(value) is not str or len(value.encode("utf-8")) > max_bytes:
        raise ProtocolFormatError("invalid protocol message")


def _validate_bounded_integer(value: int, min_val: int, max_val: int) -> None:
    """Require an integer within [min_val, max_val]."""
    if type(value) is not int or not (min_val <= value <= max_val):
        raise ProtocolFormatError("invalid protocol message")


def _validate_strict_bool(value: bool) -> None:
    """Require an exact boolean value."""
    if type(value) is not bool:
        raise ProtocolFormatError("invalid protocol message")


def _validate_direction(direction: str) -> None:
    """Validate message direction string."""
    if direction not in _DIRECTIONS:
        raise ProtocolFormatError("invalid protocol message")


def _validate_positive_sequence(sequence: int) -> None:
    """Validate positive sequence number."""
    if type(sequence) is not int or not (1 <= sequence <= MAX_SEQUENCE):
        raise ProtocolFormatError("invalid protocol message")


def _validate_last_sequence(sequence: int) -> None:
    """Validate last sequence number."""
    if type(sequence) is not int or not (0 <= sequence <= MAX_SEQUENCE):
        raise ProtocolFormatError("invalid protocol message")


def _validate_session_key(key: bytes) -> bytes:
    """Validate session key length."""
    if type(key) is not bytes or len(key) != _SECRET_BYTES:
        raise ProtocolFormatError("invalid protocol message")
    return key


def _require_string(value: object) -> str:
    """Require string value."""
    if type(value) is not str:
        raise ProtocolFormatError("invalid protocol message")
    return value


def _require_exact_object(document: object, expected_keys: set) -> Dict[str, object]:
    """Require exact dict keys."""
    if type(document) is not dict or set(document.keys()) != expected_keys:
        raise ProtocolFormatError("invalid protocol message")
    return document


def _require_wire_protocol_tokens(protocols: object) -> Tuple[str, ...]:
    """Validate wire protocol tokens."""
    try:
        return validate_protocol_tokens(protocols)
    except ProtocolFormatError:
        raise
    except Exception:
        raise ProtocolFormatError("invalid protocol message") from None


def _require_wire_feature_ids(features: object) -> Tuple[str, ...]:
    """Validate wire feature IDs."""
    try:
        return validate_feature_ids(features)
    except ProtocolFormatError:
        raise
    except Exception:
        raise ProtocolFormatError("invalid protocol message") from None


def _require_message(
    document: object, expected_keys: set, expected_type: str
) -> Dict[str, object]:
    """Validate base protocol message format."""
    if type(document) is not dict or set(document.keys()) != expected_keys:
        raise ProtocolFormatError("invalid protocol message")
    v = document.get("version")
    if type(v) is not int or v != PROTOCOL_VERSION:
        raise ProtocolFormatError("invalid protocol message")
    if document.get("type") != expected_type:
        raise ProtocolFormatError("invalid protocol message")
    return document


def _require_versioned_message(
    document: object, expected_keys: set, expected_type: str, version: int
) -> Dict[str, object]:
    """Validate versioned message format."""
    if type(document) is not dict or set(document.keys()) != expected_keys:
        raise ProtocolFormatError("invalid protocol message")
    v = document.get("version")
    if type(v) is not int or v != version:
        raise ProtocolFormatError("invalid protocol message")
    if document.get("type") != expected_type:
        raise ProtocolFormatError("invalid protocol message")
    return document


def _require_application_message(
    document: object, expected_keys: set, expected_type: str
) -> Dict[str, object]:
    """Validate application message format."""
    if type(document) is not dict or set(document.keys()) != expected_keys:
        raise ProtocolFormatError("invalid protocol message")
    s = document.get("schema")
    if type(s) is not int or s != 1:
        raise ProtocolFormatError("invalid protocol message")
    if document.get("type") != expected_type:
        raise ProtocolFormatError("invalid protocol message")
    return document


__all__ = [
    "generate_destination_id",
    "generate_link_id",
    "negotiate_features",
    "select_websocket_subprotocol",
    "validate_destination_id",
    "validate_feature_ids",
    "validate_link_id",
    "validate_nonce",
    "validate_pairing_key",
    "validate_protocol_tokens",
]
