"""Handshake wire message builders and parsers.

The module is deliberately host-neutral and uses only Python 3.9-compatible
standard-library features.
"""

from __future__ import annotations

import hmac
from typing import Dict, Sequence

from ._handshake_messages import (
    _require_context,
    _require_v2_context,
    _require_v2_selection,
)
from ._serializers import _normalize_payload
from .crypto import (
    _token_bytes,
    create_client_proof,
    create_server_proof,
    create_v2_client_proof,
    create_v2_server_proof,
    derive_session_id,
    derive_v2_session_id,
    make_handshake_context,
    make_v2_handshake_context,
    verify_client_proof,
    verify_server_proof,
    verify_v2_client_proof,
    verify_v2_server_proof,
)
from .messages import (
    _APPLICATION_READY_KEYS,
    _AUTHENTICATE_KEYS,
    _CHALLENGE_KEYS,
    _HELLO_KEYS,
    _READY_KEYS,
    _V2_CHALLENGE_KEYS,
    _V2_HELLO_KEYS,
    PROTOCOL_VERSION,
    PROTOCOL_VERSION_V2,
    ClientHello,
    HandshakeContext,
    ProtocolAuthenticationError,
    ProtocolFormatError,
    ProtocolSelection,
    V2ClientHello,
    V2HandshakeContext,
)
from .validation import (
    _require_application_message,
    _require_message,
    _require_string,
    _require_versioned_message,
    _require_wire_feature_ids,
    _require_wire_protocol_tokens,
    validate_feature_ids,
    validate_protocol_tokens,
)

__all__ = [
    "accept_challenge",
    "accept_v2_challenge",
    "build_application_ready",
    "build_authenticate",
    "build_challenge",
    "build_hello",
    "build_ready",
    "build_v2_authenticate",
    "build_v2_challenge",
    "build_v2_hello",
    "build_v2_ready",
    "parse_application_ready",
    "parse_hello",
    "parse_v2_hello",
    "verify_authenticate",
    "verify_ready",
    "verify_v2_authenticate",
    "verify_v2_ready",
]


def build_hello(
    link_id: str,
    destination_id: str,
    client_nonce: str,
) -> Dict[str, object]:
    """Build the first client handshake message."""
    hello = ClientHello(link_id, destination_id, client_nonce)
    return {
        "version": PROTOCOL_VERSION,
        "type": "hello",
        "link_id": hello.link_id,
        "destination_id": hello.destination_id,
        "client_nonce": hello.client_nonce,
    }


def parse_hello(document: object) -> ClientHello:
    """Parse an exact client hello document."""
    data = _require_message(document, _HELLO_KEYS, "hello")
    return ClientHello(
        link_id=_require_string(data["link_id"]),
        destination_id=_require_string(data["destination_id"]),
        client_nonce=_require_string(data["client_nonce"]),
    )


def build_challenge(
    pairing_key: str,
    context: HandshakeContext,
) -> Dict[str, object]:
    """Build the server challenge and its transcript-bound proof."""
    _require_context(context)
    return {
        "version": PROTOCOL_VERSION,
        "type": "challenge",
        "server_nonce": context.server_nonce,
        "server_proof": create_server_proof(pairing_key, context),
    }


def accept_challenge(
    pairing_key: str,
    hello: ClientHello,
    document: object,
) -> HandshakeContext:
    """Parse and authenticate a server challenge, returning its context."""
    if not isinstance(hello, ClientHello):
        raise ProtocolFormatError("invalid protocol message")
    data = _require_message(document, _CHALLENGE_KEYS, "challenge")
    server_nonce = _require_string(data["server_nonce"])
    server_proof = _require_string(data["server_proof"])
    context = make_handshake_context(hello, server_nonce)
    verify_server_proof(pairing_key, context, server_proof)
    return context


def build_authenticate(
    pairing_key: str,
    context: HandshakeContext,
) -> Dict[str, object]:
    """Build the client's response to an authenticated challenge."""
    _require_context(context)
    return {
        "version": PROTOCOL_VERSION,
        "type": "authenticate",
        "client_proof": create_client_proof(pairing_key, context),
    }


def verify_authenticate(
    pairing_key: str,
    context: HandshakeContext,
    document: object,
) -> None:
    """Parse and authenticate the client's handshake response."""
    _require_context(context)
    data = _require_message(document, _AUTHENTICATE_KEYS, "authenticate")
    verify_client_proof(pairing_key, context, data["client_proof"])


def build_ready(
    session_key: bytes,
    context: HandshakeContext,
) -> Dict[str, object]:
    """Build the final server message for an authenticated session."""
    return {
        "version": PROTOCOL_VERSION,
        "type": "ready",
        "session_id": derive_session_id(session_key, context),
    }


def verify_ready(
    session_key: bytes,
    context: HandshakeContext,
    document: object,
) -> str:
    """Verify the final secret-bound session identifier in constant time."""
    data = _require_message(document, _READY_KEYS, "ready")
    received = _token_bytes(data["session_id"])
    expected_id = derive_session_id(session_key, context)
    expected = _token_bytes(expected_id)
    if not hmac.compare_digest(received, expected):
        raise ProtocolAuthenticationError("protocol authentication failed")
    return expected_id


def build_v2_hello(
    link_id: str,
    destination_id: str,
    client_nonce: str,
    *,
    client_protocols: Sequence[str],
    selected_protocol: str,
    client_features: Sequence[str],
) -> Dict[str, object]:
    """Build the authenticated repeat of the HTTP protocol negotiation."""
    hello = V2ClientHello(
        link_id=link_id,
        destination_id=destination_id,
        client_nonce=client_nonce,
        client_protocols=validate_protocol_tokens(client_protocols),
        selected_protocol=selected_protocol,
        client_features=validate_feature_ids(client_features),
    )
    return {
        "version": PROTOCOL_VERSION_V2,
        "type": "hello",
        "link_id": hello.link_id,
        "destination_id": hello.destination_id,
        "client_nonce": hello.client_nonce,
        "client_protocols": list(hello.client_protocols),
        "selected_protocol": hello.selected_protocol,
        "client_features": list(hello.client_features),
    }


def parse_v2_hello(document: object) -> V2ClientHello:
    """Parse one exact v2 client hello."""
    data = _require_versioned_message(
        document,
        _V2_HELLO_KEYS,
        "hello",
        PROTOCOL_VERSION_V2,
    )
    return V2ClientHello(
        link_id=_require_string(data["link_id"]),
        destination_id=_require_string(data["destination_id"]),
        client_nonce=_require_string(data["client_nonce"]),
        client_protocols=_require_wire_protocol_tokens(data["client_protocols"]),
        selected_protocol=_require_string(data["selected_protocol"]),
        client_features=_require_wire_feature_ids(data["client_features"]),
    )


def build_v2_challenge(
    pairing_key: str,
    context: V2HandshakeContext,
) -> Dict[str, object]:
    """Build the exact v2 server selection and transcript-bound proof."""
    validated = _require_v2_context(context)
    return {
        "version": PROTOCOL_VERSION_V2,
        "type": "challenge",
        "server_nonce": validated.server_nonce,
        "server_protocols": list(validated.server_protocols),
        "selected_protocol": validated.selected_protocol,
        "server_features": list(validated.server_features),
        "selected_features": list(validated.selected_features),
        "server_proof": create_v2_server_proof(pairing_key, validated),
    }


def accept_v2_challenge(
    pairing_key: str,
    hello: V2ClientHello,
    document: object,
) -> V2HandshakeContext:
    """Parse and authenticate one deterministic v2 server selection."""
    if not isinstance(hello, V2ClientHello):
        raise ProtocolFormatError("invalid protocol message")
    data = _require_versioned_message(
        document,
        _V2_CHALLENGE_KEYS,
        "challenge",
        PROTOCOL_VERSION_V2,
    )
    context = make_v2_handshake_context(
        hello,
        server_nonce=_require_string(data["server_nonce"]),
        server_protocols=_require_wire_protocol_tokens(data["server_protocols"]),
        server_features=_require_wire_feature_ids(data["server_features"]),
    )
    selected_features = _require_wire_feature_ids(data["selected_features"])
    if (
        data["selected_protocol"] != context.selected_protocol
        or selected_features != context.selected_features
    ):
        raise ProtocolFormatError("invalid protocol message")
    verify_v2_server_proof(pairing_key, context, data["server_proof"])
    return context


def build_v2_authenticate(
    pairing_key: str,
    context: V2HandshakeContext,
) -> Dict[str, object]:
    """Build the v2 client's proof of the authenticated selection."""
    validated = _require_v2_context(context)
    return {
        "version": PROTOCOL_VERSION_V2,
        "type": "authenticate",
        "client_proof": create_v2_client_proof(pairing_key, validated),
    }


def verify_v2_authenticate(
    pairing_key: str,
    context: V2HandshakeContext,
    document: object,
) -> None:
    """Parse and authenticate the v2 client's response."""
    validated = _require_v2_context(context)
    data = _require_versioned_message(
        document,
        _AUTHENTICATE_KEYS,
        "authenticate",
        PROTOCOL_VERSION_V2,
    )
    verify_v2_client_proof(pairing_key, validated, data["client_proof"])


def build_v2_ready(
    session_key: bytes,
    context: V2HandshakeContext,
) -> Dict[str, object]:
    """Build the final v2 server handshake message."""
    return {
        "version": PROTOCOL_VERSION_V2,
        "type": "ready",
        "session_id": derive_v2_session_id(session_key, context),
    }


def verify_v2_ready(
    session_key: bytes,
    context: V2HandshakeContext,
    document: object,
) -> str:
    """Verify the final v2 secret-bound session identifier."""
    data = _require_versioned_message(
        document,
        _READY_KEYS,
        "ready",
        PROTOCOL_VERSION_V2,
    )
    received = _token_bytes(data["session_id"])
    expected_id = derive_v2_session_id(session_key, context)
    expected = _token_bytes(expected_id)
    if not hmac.compare_digest(received, expected):
        raise ProtocolAuthenticationError("protocol authentication failed")
    return expected_id


def build_application_ready(
    selection: ProtocolSelection,
) -> Dict[str, object]:
    """Build the feature-independent v2 application lifecycle message."""
    _require_v2_selection(selection)
    return {"schema": 1, "type": "application_ready"}


def parse_application_ready(
    selection: ProtocolSelection,
    document: object,
) -> None:
    """Parse the exact feature-independent v2 lifecycle message."""
    _require_v2_selection(selection)
    _require_application_message(
        _normalize_payload(document),
        _APPLICATION_READY_KEYS,
        "application_ready",
    )
