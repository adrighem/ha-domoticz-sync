"""Shared bridge transport helpers and session state (dependency-free leaf)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Protocol

from aiohttp import WSCloseCode, WSMsgType, web

from .core.protocol import (
    ProtocolError,
    ProtocolSelection,
    canonical_json_dumps,
    canonical_json_loads,
    validate_nonce,
)

_ControlResultsMap = dict[str, tuple[object, dict[str, object]]]
_InFlightControlsMap = dict[str, tuple[object, asyncio.Future[dict[str, object]]]]


class _PeerClosed(Exception):
    """The peer closed its connection normally."""


class _DeactivatableSession(Protocol):
    """Application-facing session handle that can be detached."""

    def _deactivate(self) -> None:
        """Prevent further application traffic."""


@dataclass(slots=True)
class BridgeSession:
    """One mutually authenticated Domoticz connection."""

    entry_id: str
    link_id: str
    destination_id: str
    session_id: str
    websocket: web.WebSocketResponse = field(repr=False)
    session_key: bytes = field(repr=False)
    selection: ProtocolSelection | None = None
    client_sequence: int = 0
    server_sequence: int = 0
    ready: bool = False
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    application_session: _DeactivatableSession | None = field(default=None, repr=False)
    application_task: asyncio.Task[None] | None = field(default=None, repr=False)
    control_results: _ControlResultsMap = field(default_factory=dict, repr=False)
    in_flight_controls: _InFlightControlsMap = field(default_factory=dict, repr=False)
    control_timestamps: list[float] = field(default_factory=list, repr=False)


def _validate_heartbeat_payload(payload: dict[str, object]) -> str:
    """Validate an exact signed application heartbeat payload."""
    if set(payload) != {"id", "type"}:
        raise ProtocolError("invalid protocol message")
    heartbeat_id = payload["id"]
    validate_nonce(heartbeat_id)
    assert isinstance(heartbeat_id, str)
    return heartbeat_id


def _raise_normalized_session_error(error: BaseException) -> None:
    """Raise expected transport failures."""
    if not isinstance(error, Exception) or isinstance(
        error, (_PeerClosed, ProtocolError, TimeoutError, ConnectionError)
    ):
        raise error
    raise ProtocolError("application session is unavailable") from None


async def _async_receive_document(websocket: web.WebSocketResponse) -> object:
    """Receive one canonical text document or classify a closed peer."""
    message = await websocket.receive()
    if message.type is WSMsgType.TEXT:
        return canonical_json_loads(message.data)
    if message.type in {
        WSMsgType.CLOSE,
        WSMsgType.CLOSED,
        WSMsgType.CLOSING,
        WSMsgType.ERROR,
    }:
        raise _PeerClosed
    raise ProtocolError("invalid protocol message")


async def _async_send_document(
    websocket: web.WebSocketResponse,
    document: object,
) -> None:
    """Send one canonical text document."""
    await websocket.send_str(canonical_json_dumps(document))


async def _async_close(
    websocket: web.WebSocketResponse,
    code: WSCloseCode,
    message: bytes,
) -> None:
    """Close a WebSocket without leaking protocol or credential details."""
    if not websocket.closed:
        await websocket.close(code=code, message=message)
