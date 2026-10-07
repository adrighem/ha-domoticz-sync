"""HTTP view and WebSocket endpoint for the Domoticz companion plugin."""

from __future__ import annotations

import asyncio
from http import HTTPStatus
from typing import TYPE_CHECKING, Final

from aiohttp import WSCloseCode, WSMsgType, web
from homeassistant.components.http import HomeAssistantView

from .const import DOMAIN
from .core.protocol import (
    MAX_INVENTORY_PAGES,
    SUPPORTED_WEBSOCKET_SUBPROTOCOLS,
    ProtocolError,
    canonical_json_dumps,
    canonical_json_loads,
    select_websocket_subprotocol,
    validate_nonce,
    validate_protocol_tokens,
)

if TYPE_CHECKING:
    from .bridge import DomoticzBridgeManager

BRIDGE_WEBSOCKET_PATH: Final = "/api/domoticz_sync/websocket"
MAX_BRIDGE_MESSAGE_BYTES: Final = 64 * 1024
PREPARE_TIMEOUT: Final = 5.0

MAX_APPLICATION_INBOX_MESSAGES: Final = MAX_INVENTORY_PAGES
MAX_CONTROL_RESULTS: Final = 256
INVENTORY_TIMEOUT: Final = 10.0
HEARTBEAT_INTERVAL: Final = 30.0
HEARTBEAT_RESPONSE_TIMEOUT: Final = 10.0
MAX_CONTROLS_PER_WINDOW: Final = 30
CONTROL_WINDOW_SECONDS: Final = 5.0


class _PeerClosed(Exception):
    """The peer closed its connection normally."""


def _validate_heartbeat_payload(payload: dict[str, object]) -> str:
    """Validate an exact signed application heartbeat payload."""
    if set(payload) != {"id", "type"}:
        raise ProtocolError("invalid protocol message")
    heartbeat_id = payload["id"]
    validate_nonce(heartbeat_id)
    assert isinstance(heartbeat_id, str)
    return heartbeat_id


def _parse_ping(payload: dict[str, object]) -> str:
    """Parse bridge exact heartbeat request shape."""
    if set(payload) != {"id", "type"} or payload["type"] != "ping":
        raise ProtocolError("invalid protocol message")
    ping_id = payload["id"]
    validate_nonce(ping_id)
    assert isinstance(ping_id, str)
    return ping_id


def _raise_normalized_session_error(error: BaseException) -> None:
    """Raise expected transport failures."""
    if not isinstance(error, Exception) or isinstance(
        error, (_PeerClosed, ProtocolError, TimeoutError, ConnectionError)
    ):
        raise error
    raise ProtocolError("application session is unavailable") from None


def _request_protocols(request: web.Request) -> tuple[str, ...]:
    """Normalize the ordered WebSocket protocol offer from HTTP headers."""
    header_values = request.headers.getall("Sec-WebSocket-Protocol", ())
    if not header_values:
        return ()
    tokens = [
        token.strip()
        for header_value in header_values
        for token in header_value.split(",")
    ]
    return validate_protocol_tokens(tokens)


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


class DomoticzBridgeView(HomeAssistantView):
    """Unauthenticated HTTP upgrade endpoint with protocol-level authentication."""

    name = f"api:{DOMAIN}:websocket"
    url = BRIDGE_WEBSOCKET_PATH
    requires_auth = False
    cors_allowed = False

    def __init__(self, manager: DomoticzBridgeManager) -> None:
        """Initialize the singleton view."""
        self._manager = manager

    async def get(self, request: web.Request) -> web.StreamResponse:
        """Upgrade one bounded Domoticz bridge connection."""
        if not await self._manager.async_reserve_handshake():
            return web.Response(status=HTTPStatus.SERVICE_UNAVAILABLE)

        try:
            client_protocols = _request_protocols(request)
            if (
                client_protocols
                and select_websocket_subprotocol(
                    client_protocols,
                    SUPPORTED_WEBSOCKET_SUBPROTOCOLS,
                )
                is None
            ):
                await self._manager.async_release_handshake()
                return web.Response(status=HTTPStatus.BAD_REQUEST)
        except ProtocolError:
            await self._manager.async_release_handshake()
            return web.Response(status=HTTPStatus.BAD_REQUEST)

        websocket = web.WebSocketResponse(
            autoping=True,
            compress=False,
            max_msg_size=MAX_BRIDGE_MESSAGE_BYTES,
            protocols=SUPPORTED_WEBSOCKET_SUBPROTOCOLS,
        )
        try:
            async with asyncio.timeout(PREPARE_TIMEOUT):
                await websocket.prepare(request)
        except BaseException:
            await self._manager.async_release_handshake()
            raise

        await self._manager.async_handle_reserved(
            websocket,
            client_protocols=client_protocols,
            selected_protocol=websocket.ws_protocol,
        )
        return websocket
