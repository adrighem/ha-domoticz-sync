"""HTTP view and WebSocket endpoint for the Domoticz companion plugin."""

from __future__ import annotations

import asyncio
from http import HTTPStatus
from typing import Final, Protocol

from aiohttp import web
from homeassistant.components.http import HomeAssistantView

from .const import DOMAIN
from .core.protocol import (
    SUPPORTED_WEBSOCKET_SUBPROTOCOLS,
    ProtocolError,
    select_websocket_subprotocol,
    validate_nonce,
    validate_protocol_tokens,
)

BRIDGE_WEBSOCKET_PATH: Final = "/api/domoticz_sync/websocket"
MAX_BRIDGE_MESSAGE_BYTES: Final = 64 * 1024
PREPARE_TIMEOUT: Final = 5.0


class _HandshakeManager(Protocol):
    """Manager operations used by the bridge view."""

    async def async_reserve_handshake(self) -> bool:
        """Reserve one bounded unauthenticated handshake slot."""

    async def async_release_handshake(self) -> None:
        """Release a previously reserved handshake slot."""

    async def async_handle_reserved(
        self,
        websocket: web.WebSocketResponse,
        *,
        client_protocols: tuple[str, ...],
        selected_protocol: str | None,
    ) -> None:
        """Authenticate and run a connection with a reserved slot."""


def _parse_ping(payload: dict[str, object]) -> str:
    """Parse bridge exact heartbeat request shape."""
    if set(payload) != {"id", "type"} or payload["type"] != "ping":
        raise ProtocolError("invalid protocol message")
    ping_id = payload["id"]
    validate_nonce(ping_id)
    assert isinstance(ping_id, str)
    return ping_id


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


class DomoticzBridgeView(HomeAssistantView):
    """Unauthenticated HTTP upgrade endpoint with protocol-level authentication."""

    name = f"api:{DOMAIN}:websocket"
    url = BRIDGE_WEBSOCKET_PATH
    requires_auth = False
    cors_allowed = False

    def __init__(self, manager: _HandshakeManager) -> None:
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
