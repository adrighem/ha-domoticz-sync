"""Cryptographic primitives, handshake contexts, proofs, and envelope signing.

The module is deliberately host-neutral and uses only Python 3.9-compatible
standard-library features.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Dict

from ._crypto_tokens import (
    _encode_token,
    _normalize_payload,
    _pairing_key_bytes,
    _token_bytes,
)
from .codec import canonical_json_bytes
from .messages import (
    _ENVELOPE_KEYS,
    PAIRING_KEY_BITS,
    PROTOCOL_VERSION,
    PROTOCOL_VERSION_V2,
    ClientHello,
    HandshakeContext,
    ProtocolAuthenticationError,
    ProtocolFormatError,
    ProtocolSequenceError,
    V2ClientHello,
    V2HandshakeContext,
    VerifiedEnvelope,
)
from .validation import (
    _SECRET_BYTES,
    _require_context,
    _require_string,
    _require_v2_context,
    _require_versioned_message,
    _validate_direction,
    _validate_last_sequence,
    _validate_positive_sequence,
    _validate_session_key,
    select_websocket_subprotocol,
    validate_nonce,
)

_PROTOCOL_DOMAIN = b"ha-domoticz-sync/protocol/v1/"
_CLIENT_PROOF_DOMAIN = _PROTOCOL_DOMAIN + b"client-proof\x00"
_SERVER_PROOF_DOMAIN = _PROTOCOL_DOMAIN + b"server-proof\x00"
_SESSION_SALT_DOMAIN = _PROTOCOL_DOMAIN + b"session-salt\x00"
_SESSION_KEY_DOMAIN = _PROTOCOL_DOMAIN + b"session-key\x00"
_SESSION_ID_DOMAIN = _PROTOCOL_DOMAIN + b"session-id\x00"
_ENVELOPE_DOMAIN = _PROTOCOL_DOMAIN + b"envelope\x00"

_V2_PROTOCOL_DOMAIN = b"ha-domoticz-sync/protocol/v2/"
_V2_CLIENT_PROOF_DOMAIN = _V2_PROTOCOL_DOMAIN + b"client-proof\x00"
_V2_SERVER_PROOF_DOMAIN = _V2_PROTOCOL_DOMAIN + b"server-proof\x00"
_V2_SESSION_SALT_DOMAIN = _V2_PROTOCOL_DOMAIN + b"session-salt\x00"
_V2_SESSION_KEY_DOMAIN = _V2_PROTOCOL_DOMAIN + b"session-key\x00"
_V2_SESSION_ID_DOMAIN = _V2_PROTOCOL_DOMAIN + b"session-id\x00"
_V2_ENVELOPE_DOMAIN = _V2_PROTOCOL_DOMAIN + b"envelope\x00"

__all__ = [
    "create_client_proof",
    "create_server_proof",
    "create_v2_client_proof",
    "create_v2_server_proof",
    "derive_session_id",
    "derive_session_key",
    "derive_v2_session_id",
    "derive_v2_session_key",
    "generate_nonce",
    "generate_pairing_key",
    "generate_request_id",
    "make_handshake_context",
    "make_v2_handshake_context",
    "sign_envelope",
    "verify_client_proof",
    "verify_envelope",
    "verify_server_proof",
    "verify_v2_client_proof",
    "verify_v2_server_proof",
]


def generate_pairing_key() -> str:
    """Generate a 256-bit canonical URL-safe pairing key."""
    return _encode_token(secrets.token_bytes(_SECRET_BYTES))


def generate_nonce() -> str:
    """Generate a 256-bit canonical URL-safe handshake nonce."""
    return _encode_token(secrets.token_bytes(PAIRING_KEY_BITS // 8))


def generate_request_id() -> str:
    """Generate a strong correlation ID accepted by the identifier schema."""
    return "request_" + generate_nonce()


def make_handshake_context(
    hello: ClientHello,
    server_nonce: str,
) -> HandshakeContext:
    """Combine a validated hello with the server's fresh nonce."""
    if not isinstance(hello, ClientHello):
        raise ProtocolFormatError("invalid protocol message")
    return HandshakeContext(
        link_id=hello.link_id,
        destination_id=hello.destination_id,
        client_nonce=hello.client_nonce,
        server_nonce=server_nonce,
    )


def make_v2_handshake_context(
    hello: V2ClientHello,
    server_nonce: str,
    *,
    server_protocols: tuple[str, ...],
    server_features: tuple[str, ...],
) -> V2HandshakeContext:
    """Combine a validated v2 hello offer with the server response."""
    if not isinstance(hello, V2ClientHello):
        raise ProtocolFormatError("invalid protocol message")
    validate_nonce(server_nonce)
    selected_protocol = select_websocket_subprotocol(
        hello.client_protocols,
        server_protocols,
    )
    if selected_protocol is None:
        raise ProtocolFormatError("invalid protocol message")

    from .validation import negotiate_features

    selected_features = negotiate_features(
        hello.client_features,
        server_features,
    )
    return V2HandshakeContext(
        link_id=hello.link_id,
        destination_id=hello.destination_id,
        client_nonce=hello.client_nonce,
        server_nonce=server_nonce,
        client_protocols=hello.client_protocols,
        server_protocols=server_protocols,
        selected_protocol=selected_protocol,
        client_features=hello.client_features,
        server_features=server_features,
        selected_features=selected_features,
    )


def create_client_proof(
    pairing_key: str,
    context: HandshakeContext,
) -> str:
    """Create the Domoticz proof for one complete handshake transcript."""
    return _create_proof(pairing_key, context, _CLIENT_PROOF_DOMAIN)


def verify_client_proof(
    pairing_key: str,
    context: HandshakeContext,
    proof: object,
) -> None:
    """Verify a Domoticz proof in constant time."""
    _verify_proof(pairing_key, context, proof, _CLIENT_PROOF_DOMAIN)


def create_server_proof(
    pairing_key: str,
    context: HandshakeContext,
) -> str:
    """Create the Home Assistant proof for one complete transcript."""
    return _create_proof(pairing_key, context, _SERVER_PROOF_DOMAIN)


def verify_server_proof(
    pairing_key: str,
    context: HandshakeContext,
    proof: object,
) -> None:
    """Verify a Home Assistant proof in constant time."""
    _verify_proof(pairing_key, context, proof, _SERVER_PROOF_DOMAIN)


def create_v2_client_proof(
    pairing_key: str,
    context: V2HandshakeContext,
) -> str:
    """Create the Domoticz v2 proof for one complete negotiation transcript."""
    return _create_v2_proof(pairing_key, context, _V2_CLIENT_PROOF_DOMAIN)


def verify_v2_client_proof(
    pairing_key: str,
    context: V2HandshakeContext,
    proof: object,
) -> None:
    """Verify a Domoticz v2 proof in constant time."""
    _verify_v2_proof(pairing_key, context, proof, _V2_CLIENT_PROOF_DOMAIN)


def create_v2_server_proof(
    pairing_key: str,
    context: V2HandshakeContext,
) -> str:
    """Create the Home Assistant v2 proof for one complete negotiation."""
    return _create_v2_proof(pairing_key, context, _V2_SERVER_PROOF_DOMAIN)


def verify_v2_server_proof(
    pairing_key: str,
    context: V2HandshakeContext,
    proof: object,
) -> None:
    """Verify a Home Assistant v2 proof in constant time."""
    _verify_v2_proof(pairing_key, context, proof, _V2_SERVER_PROOF_DOMAIN)


def derive_session_key(
    pairing_key: str,
    context: HandshakeContext,
) -> bytes:
    """Derive a unique 256-bit session key using an HKDF-style expansion."""
    key = _pairing_key_bytes(pairing_key)
    transcript = _transcript_bytes(context)
    salt = hashlib.sha256(_SESSION_SALT_DOMAIN + transcript).digest()
    extracted = hmac.new(salt, key, hashlib.sha256).digest()
    return hmac.new(
        extracted,
        _SESSION_KEY_DOMAIN + transcript + b"\x01",
        hashlib.sha256,
    ).digest()


def derive_session_id(
    session_key: bytes,
    context: HandshakeContext,
) -> str:
    """Derive an unpredictable identifier bound to one authenticated session."""
    key = _validate_session_key(session_key)
    digest = hmac.new(
        key,
        _SESSION_ID_DOMAIN + _transcript_bytes(context),
        hashlib.sha256,
    ).digest()
    return _encode_token(digest)


def derive_v2_session_key(
    pairing_key: str,
    context: V2HandshakeContext,
) -> bytes:
    """Derive a v2 session key bound to protocol and feature negotiation."""
    key = _pairing_key_bytes(pairing_key)
    transcript = _v2_transcript_bytes(context)
    salt = hashlib.sha256(_V2_SESSION_SALT_DOMAIN + transcript).digest()
    extracted = hmac.new(salt, key, hashlib.sha256).digest()
    return hmac.new(
        extracted,
        _V2_SESSION_KEY_DOMAIN + transcript + b"\x01",
        hashlib.sha256,
    ).digest()


def derive_v2_session_id(
    session_key: bytes,
    context: V2HandshakeContext,
) -> str:
    """Derive the v2 secret-bound identifier for one negotiated session."""
    key = _validate_session_key(session_key)
    digest = hmac.new(
        key,
        _V2_SESSION_ID_DOMAIN + _v2_transcript_bytes(context),
        hashlib.sha256,
    ).digest()
    return _encode_token(digest)


def sign_envelope(
    session_key: bytes,
    *,
    protocol_version: int,
    direction: str,
    session_id: str,
    sequence: int,
    payload: object,
) -> Dict[str, object]:
    """Build and sign one directional application envelope."""
    key = _validate_session_key(session_key)
    domain = _envelope_domain(protocol_version)
    _validate_direction(direction)
    _token_bytes(session_id)
    _validate_positive_sequence(sequence)
    normalized_payload = _normalize_payload(payload)
    unsigned = _unsigned_envelope(
        protocol_version,
        direction,
        session_id,
        sequence,
        normalized_payload,
    )
    signature = hmac.new(
        key,
        domain + canonical_json_bytes(unsigned),
        hashlib.sha256,
    ).digest()
    envelope = dict(unsigned)
    envelope["signature"] = _encode_token(signature)
    return envelope


def verify_envelope(
    session_key: bytes,
    document: object,
    *,
    protocol_version: int,
    expected_direction: str,
    expected_session_id: str,
    last_sequence: int,
) -> VerifiedEnvelope:
    """Authenticate one envelope and require the exact next sequence number."""
    key = _validate_session_key(session_key)
    domain = _envelope_domain(protocol_version)
    _validate_direction(expected_direction)
    expected_session = _token_bytes(expected_session_id)
    _validate_last_sequence(last_sequence)

    data = _require_versioned_message(
        document,
        _ENVELOPE_KEYS,
        "message",
        protocol_version,
    )
    direction = _require_string(data["direction"])
    _validate_direction(direction)
    session_id = _require_string(data["session_id"])
    received_session = _token_bytes(session_id)
    sequence = data["sequence"]
    _validate_positive_sequence(sequence)
    payload = _normalize_payload(data["payload"])
    signature = _token_bytes(data["signature"])

    unsigned = _unsigned_envelope(
        protocol_version,
        direction,
        session_id,
        sequence,
        payload,
    )
    expected_signature = hmac.new(
        key,
        domain + canonical_json_bytes(unsigned),
        hashlib.sha256,
    ).digest()
    if not hmac.compare_digest(signature, expected_signature):
        raise ProtocolAuthenticationError("protocol authentication failed")
    if direction != expected_direction or not hmac.compare_digest(
        received_session,
        expected_session,
    ):
        raise ProtocolAuthenticationError("protocol authentication failed")
    if sequence != last_sequence + 1:
        raise ProtocolSequenceError("invalid protocol sequence")

    return VerifiedEnvelope(
        session_id=session_id,
        direction=direction,
        sequence=sequence,
        payload=payload,
    )


def _transcript_bytes(context: HandshakeContext) -> bytes:
    """Return the canonical public handshake transcript."""
    validated = _require_context(context)
    return canonical_json_bytes(
        {
            "version": PROTOCOL_VERSION,
            "link_id": validated.link_id,
            "destination_id": validated.destination_id,
            "client_nonce": validated.client_nonce,
            "server_nonce": validated.server_nonce,
        }
    )


def _v2_transcript_bytes(context: V2HandshakeContext) -> bytes:
    """Return the canonical complete v2 negotiation transcript."""
    validated = _require_v2_context(context)
    return canonical_json_bytes(
        {
            "version": PROTOCOL_VERSION_V2,
            "link_id": validated.link_id,
            "destination_id": validated.destination_id,
            "client_nonce": validated.client_nonce,
            "server_nonce": validated.server_nonce,
            "client_protocols": list(validated.client_protocols),
            "server_protocols": list(validated.server_protocols),
            "selected_protocol": validated.selected_protocol,
            "client_features": list(validated.client_features),
            "server_features": list(validated.server_features),
            "selected_features": list(validated.selected_features),
        }
    )


def _create_proof(
    pairing_key: str,
    context: HandshakeContext,
    domain: bytes,
) -> str:
    """Create one role-separated transcript proof."""
    key = _pairing_key_bytes(pairing_key)
    proof = hmac.new(
        key,
        domain + _transcript_bytes(context),
        hashlib.sha256,
    ).digest()
    return _encode_token(proof)


def _verify_proof(
    pairing_key: str,
    context: HandshakeContext,
    proof: object,
    domain: bytes,
) -> None:
    """Authenticate one role-separated proof in constant time."""
    received = _token_bytes(proof)
    expected = _token_bytes(_create_proof(pairing_key, context, domain))
    if not hmac.compare_digest(received, expected):
        raise ProtocolAuthenticationError("protocol authentication failed")


def _create_v2_proof(
    pairing_key: str,
    context: V2HandshakeContext,
    domain: bytes,
) -> str:
    """Create one role-separated v2 negotiation proof."""
    key = _pairing_key_bytes(pairing_key)
    proof = hmac.new(
        key,
        domain + _v2_transcript_bytes(context),
        hashlib.sha256,
    ).digest()
    return _encode_token(proof)


def _verify_v2_proof(
    pairing_key: str,
    context: V2HandshakeContext,
    proof: object,
    domain: bytes,
) -> None:
    """Authenticate one v2 proof in constant time."""
    received = _token_bytes(proof)
    expected = _token_bytes(_create_v2_proof(pairing_key, context, domain))
    if not hmac.compare_digest(received, expected):
        raise ProtocolAuthenticationError("protocol authentication failed")


def _envelope_domain(protocol_version: object) -> bytes:
    """Return the role-independent MAC domain for one supported wire version."""
    if protocol_version == PROTOCOL_VERSION and type(protocol_version) is int:
        return _ENVELOPE_DOMAIN
    if protocol_version == PROTOCOL_VERSION_V2 and type(protocol_version) is int:
        return _V2_ENVELOPE_DOMAIN
    raise ProtocolFormatError("invalid protocol message")


def _unsigned_envelope(
    protocol_version: int,
    direction: str,
    session_id: str,
    sequence: int,
    payload: Dict[str, object],
) -> Dict[str, object]:
    """Return the exact application fields covered by the envelope MAC."""
    return {
        "version": protocol_version,
        "type": "message",
        "session_id": session_id,
        "direction": direction,
        "sequence": sequence,
        "payload": payload,
    }
