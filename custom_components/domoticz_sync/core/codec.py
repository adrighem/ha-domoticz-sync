"""Deterministic JSON serialization and parsing for the wire protocol.

The module is deliberately host-neutral and uses only Python 3.9-compatible
standard-library features.
"""

from __future__ import annotations

import json
import math

from ._constants import (
    MAX_JSON_DEPTH,
    MAX_MESSAGE_BYTES,
    MAX_SAFE_INTEGER,
)

__all__ = [
    "canonical_json_bytes",
    "canonical_json_dumps",
    "canonical_json_loads",
]


def canonical_json_dumps(value: object) -> str:
    """Serialize one value to the protocol's deterministic JSON subset."""
    from .messages import ProtocolFormatError

    try:
        _validate_json_value(value)
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        if len(encoded.encode("ascii")) > MAX_MESSAGE_BYTES:
            raise ValueError
        return encoded
    except (
        UnicodeError,
        TypeError,
        ValueError,
        OverflowError,
        RecursionError,
    ):
        raise ProtocolFormatError("invalid protocol message") from None


def canonical_json_bytes(value: object) -> bytes:
    """Serialize one value to canonical UTF-8 JSON bytes."""
    return canonical_json_dumps(value).encode("ascii")


def canonical_json_loads(document: object) -> object:
    """Parse one canonical JSON payload and require strict schema compliance."""
    from .messages import ProtocolFormatError

    try:
        if type(document) is bytes:
            if len(document) > MAX_MESSAGE_BYTES:
                raise ValueError
            raw = document.decode("utf-8")
        elif type(document) is str:
            if len(document) > MAX_MESSAGE_BYTES:
                raise ValueError
            raw = document
        else:
            raise ValueError
        parsed = json.loads(raw)
        _validate_json_value(parsed)
        if canonical_json_dumps(parsed) != raw:
            raise ValueError
        return parsed
    except (
        UnicodeError,
        TypeError,
        ValueError,
        OverflowError,
        RecursionError,
        json.JSONDecodeError,
    ):
        raise ProtocolFormatError("invalid protocol message") from None


def _validate_json_value(value: object, depth: int = 1) -> None:
    """Require strict RFC 8259 JSON types and reject non-canonical numbers."""
    if depth > MAX_JSON_DEPTH:
        raise ValueError
    if value is None or type(value) is bool:
        return
    if type(value) is int:
        if not (-MAX_SAFE_INTEGER <= value <= MAX_SAFE_INTEGER):
            raise ValueError
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError
        return
    if type(value) is str:
        if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
            raise ValueError
        return
    if type(value) is list:
        for item in value:
            _validate_json_value(item, depth + 1)
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError
            if any(0xD800 <= ord(character) <= 0xDFFF for character in key):
                raise ValueError
            _validate_json_value(item, depth + 1)
        return
    raise ValueError
