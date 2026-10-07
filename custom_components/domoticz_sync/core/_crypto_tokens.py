"""Internal token encoding and decoding helpers for protocol crypto.

The module is deliberately host-neutral and uses only Python 3.9-compatible
standard-library features.
"""

from __future__ import annotations

import base64
import re
import secrets
from typing import Dict

from ._constants import PAIRING_KEY_BITS
from .codec import canonical_json_dumps, canonical_json_loads
from .errors import ProtocolFormatError

_SECRET_BYTES = PAIRING_KEY_BITS // 8
_TOKEN_BYTES = PAIRING_KEY_BITS // 8
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
_TOKEN_DECODE_ERRORS = (TypeError, ValueError, OverflowError, AttributeError)

__all__ = [
    "_SECRET_BYTES",
    "_TOKEN_RE",
    "_decode_token",
    "_encode_token",
    "_encode_unpadded",
    "generate_nonce",
    "_normalize_payload",
    "_pairing_key_bytes",
    "_token_bytes",
]


def generate_nonce() -> str:
    """Generate a 256-bit canonical URL-safe handshake nonce."""
    return _encode_token(secrets.token_bytes(PAIRING_KEY_BITS // 8))


def _pairing_key_bytes(pairing_key: object) -> bytes:
    """Decode a validated key without exposing it in an error."""
    return _decode_token(pairing_key, _SECRET_BYTES)


def _token_bytes(value: object) -> bytes:
    """Decode one canonical 256-bit proof, session ID, or signature."""
    return _decode_token(value, _TOKEN_BYTES)


def _decode_token(value: object, expected_bytes: int) -> bytes:
    """Decode canonical unpadded base64url into an exact byte length."""
    try:
        if type(value) is not str or _TOKEN_RE.fullmatch(value) is None:
            raise ValueError
        decoded = base64.b64decode(
            value.encode("ascii") + b"=",
            altchars=b"-_",
            validate=True,
        )
        if len(decoded) != expected_bytes or _encode_unpadded(decoded) != value:
            raise ValueError
        return decoded
    except _TOKEN_DECODE_ERRORS:
        raise ProtocolFormatError("invalid protocol message") from None


def _encode_token(value: bytes) -> str:
    """Encode one 256-bit protocol token without base64 padding."""
    if type(value) is not bytes or len(value) != _TOKEN_BYTES:
        raise ProtocolFormatError("invalid protocol message")
    return _encode_unpadded(value)


def _encode_unpadded(value: bytes) -> str:
    """Encode bytes as canonical URL-safe base64 without padding."""
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _normalize_payload(payload: object) -> Dict[str, object]:
    """Validate and defensively copy one JSON object payload."""
    if type(payload) is not dict:
        raise ProtocolFormatError("invalid protocol message")
    normalized = canonical_json_loads(canonical_json_dumps(payload))
    if type(normalized) is not dict:
        raise ProtocolFormatError("invalid protocol message")
    return normalized
