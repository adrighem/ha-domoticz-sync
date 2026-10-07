"""Safe protocol failure types shared by every protocol layer.

The module is deliberately host-neutral and uses only Python 3.9-compatible
standard-library features.
"""

from __future__ import annotations

__all__ = [
    "ProtocolAuthenticationError",
    "ProtocolCompatibilityError",
    "ProtocolError",
    "ProtocolFormatError",
    "ProtocolSequenceError",
]


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
