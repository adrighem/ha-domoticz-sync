"""Handshake message dataclasses and protocol selection model.

The module is deliberately host-neutral and uses only Python 3.9-compatible
standard-library features.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from ._constants import PROTOCOL_VERSION_V2, WEBSOCKET_SUBPROTOCOL_V2


@dataclass(frozen=True)
class ClientHello:
    """The identity and fresh nonce supplied by the Domoticz client."""

    link_id: str
    destination_id: str
    client_nonce: str

    def __post_init__(self) -> None:
        """Validate direct construction as strictly as parsed input."""
        from .validation import (
            validate_destination_id,
            validate_link_id,
            validate_nonce,
        )

        validate_link_id(self.link_id)
        validate_destination_id(self.destination_id)
        validate_nonce(self.client_nonce)


@dataclass(frozen=True)
class HandshakeContext:
    """All public values bound into mutual authentication and key derivation."""

    link_id: str
    destination_id: str
    client_nonce: str
    server_nonce: str

    def __post_init__(self) -> None:
        """Validate direct construction as strictly as parsed input."""
        from .validation import (
            validate_destination_id,
            validate_link_id,
            validate_nonce,
        )

        validate_link_id(self.link_id)
        validate_destination_id(self.destination_id)
        validate_nonce(self.client_nonce)
        validate_nonce(self.server_nonce)


@dataclass(frozen=True)
class ProtocolSelection:
    """One authenticated wire version and its negotiated optional features."""

    version: int
    websocket_subprotocol: str
    features: Tuple[str, ...]

    def __post_init__(self) -> None:
        """Validate direct construction as strictly as handshake selection."""
        from .messages import ProtocolFormatError
        from .validation import validate_feature_ids

        if self.version != PROTOCOL_VERSION_V2:
            raise ProtocolFormatError("invalid protocol message")
        if self.websocket_subprotocol != WEBSOCKET_SUBPROTOCOL_V2:
            raise ProtocolFormatError("invalid protocol message")
        if type(self.features) is not tuple:
            raise ProtocolFormatError("invalid protocol message")
        validate_feature_ids(self.features)

    def supports(self, feature: str) -> bool:
        """Return whether one optional behavior was mutually negotiated."""
        from .validation import _validate_feature_id

        _validate_feature_id(feature)
        return feature in self.features


@dataclass(frozen=True)
class V2ClientHello:
    """The authenticated repeat of the HTTP WebSocket negotiation offer."""

    link_id: str
    destination_id: str
    client_nonce: str
    client_protocols: Tuple[str, ...]
    selected_protocol: str
    client_features: Tuple[str, ...]

    def __post_init__(self) -> None:
        """Validate direct construction as strictly as parsed input."""
        from .messages import ProtocolFormatError
        from .validation import (
            validate_destination_id,
            validate_feature_ids,
            validate_link_id,
            validate_nonce,
            validate_protocol_tokens,
        )

        validate_link_id(self.link_id)
        validate_destination_id(self.destination_id)
        validate_nonce(self.client_nonce)
        if (
            type(self.client_protocols) is not tuple
            or type(self.client_features) is not tuple
        ):
            raise ProtocolFormatError("invalid protocol message")
        protocols = validate_protocol_tokens(self.client_protocols)
        if (
            self.selected_protocol != WEBSOCKET_SUBPROTOCOL_V2
            or self.selected_protocol not in protocols
        ):
            raise ProtocolFormatError("invalid protocol message")
        validate_feature_ids(self.client_features)


@dataclass(frozen=True)
class V2HandshakeContext:
    """Every public v2 negotiation value bound into authentication and KDF."""

    link_id: str
    destination_id: str
    client_nonce: str
    server_nonce: str
    client_protocols: Tuple[str, ...]
    server_protocols: Tuple[str, ...]
    selected_protocol: str
    client_features: Tuple[str, ...]
    server_features: Tuple[str, ...]
    selected_features: Tuple[str, ...]

    def __post_init__(self) -> None:
        """Require one complete deterministic negotiation transcript."""
        from .messages import ProtocolFormatError
        from .validation import (
            negotiate_features,
            select_websocket_subprotocol,
            validate_destination_id,
            validate_link_id,
            validate_nonce,
        )

        validate_link_id(self.link_id)
        validate_destination_id(self.destination_id)
        validate_nonce(self.client_nonce)
        validate_nonce(self.server_nonce)
        if any(
            type(value) is not tuple
            for value in (
                self.client_protocols,
                self.server_protocols,
                self.client_features,
                self.server_features,
                self.selected_features,
            )
        ):
            raise ProtocolFormatError("invalid protocol message")
        expected_protocol = select_websocket_subprotocol(
            self.client_protocols,
            self.server_protocols,
        )
        if (
            self.selected_protocol != WEBSOCKET_SUBPROTOCOL_V2
            or self.selected_protocol != expected_protocol
        ):
            raise ProtocolFormatError("invalid protocol message")
        expected_features = negotiate_features(
            self.client_features,
            self.server_features,
        )
        if self.selected_features != expected_features:
            raise ProtocolFormatError("invalid protocol message")

    @property
    def selection(self) -> ProtocolSelection:
        """Return the immutable application contract selected by this context."""
        return ProtocolSelection(
            version=PROTOCOL_VERSION_V2,
            websocket_subprotocol=self.selected_protocol,
            features=self.selected_features,
        )


__all__ = [
    "ClientHello",
    "HandshakeContext",
    "ProtocolSelection",
    "V2ClientHello",
    "V2HandshakeContext",
]
