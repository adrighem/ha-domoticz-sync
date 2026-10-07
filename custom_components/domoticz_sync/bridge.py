"""Authenticated Home Assistant endpoint for the Domoticz companion plugin."""

from __future__ import annotations

import asyncio
from typing import Final

from aiohttp import WSCloseCode, web

from .bridge_control import DomoticzControlHandler, _parse_domoticz_color
from .bridge_session import (
    BridgeApplication,
    BridgeApplicationSession,
    BridgeConfigurationError,
    BridgeLink,
    DomoticzSessionRunner,
    _async_close,
    _async_receive_document,
    _async_send_document,
)
from .bridge_types import BridgeSession, _PeerClosed
from .bridge_view import (
    BRIDGE_WEBSOCKET_PATH,
    MAX_BRIDGE_MESSAGE_BYTES,
    DomoticzBridgeView,
)
from .core.protocol import (
    SUPPORTED_V2_FEATURES,
    SUPPORTED_WEBSOCKET_SUBPROTOCOLS,
    ProtocolAuthenticationError,
    ProtocolCompatibilityError,
    ProtocolError,
    ProtocolSelection,
    build_challenge,
    build_ready,
    build_v2_challenge,
    build_v2_ready,
    derive_session_id,
    derive_session_key,
    derive_v2_session_id,
    derive_v2_session_key,
    generate_nonce,
    make_handshake_context,
    make_v2_handshake_context,
    parse_hello,
    parse_v2_hello,
    select_websocket_subprotocol,
    verify_authenticate,
    verify_v2_authenticate,
)

MAX_PENDING_HANDSHAKES: Final = 8
FIRST_MESSAGE_TIMEOUT: Final = 3.0
AUTHENTICATION_TIMEOUT: Final = 10.0

_POLICY_CLOSE_MESSAGE: Final = b"Protocol error"
_PEER_CLOSE_MESSAGE: Final = b"Connection closed"
_SHUTDOWN_CLOSE_MESSAGE: Final = b"Bridge unavailable"


class DomoticzBridgeManager(DomoticzControlHandler, DomoticzSessionRunner):
    """Own configured links and their active authenticated sessions."""

    def __init__(self, application: BridgeApplication | None = None) -> None:
        """Initialize an empty manager."""
        self._application = application
        self._lock = asyncio.Lock()
        self._links: dict[str, BridgeLink] = {}
        self._entry_links: dict[str, str] = {}
        self._sessions: dict[str, BridgeSession] = {}
        self._pending_handshakes = 0

    async def async_register_link(
        self,
        *,
        entry_id: str,
        link_id: str,
        pairing_key: str,
    ) -> None:
        """Register or atomically replace one config entry's bridge link."""
        replacement = BridgeLink(entry_id, link_id, pairing_key)
        session_to_close: BridgeSession | None = None

        async with self._lock:
            owner = self._links.get(link_id)
            if owner is not None and owner.entry_id != entry_id:
                raise BridgeConfigurationError("bridge link is already configured")

            previous_link_id = self._entry_links.get(entry_id)
            if previous_link_id is not None and previous_link_id != link_id:
                self._links.pop(previous_link_id, None)
                session_to_close = self._sessions.pop(previous_link_id, None)
                if session_to_close is not None:
                    self._deactivate_session(session_to_close)

            current_session = self._sessions.get(link_id)
            if (
                current_session is not None
                and owner is not None
                and owner.pairing_key != pairing_key
            ):
                session_to_close = self._sessions.pop(link_id)
                self._deactivate_session(session_to_close)

            self._links[link_id] = replacement
            self._entry_links[entry_id] = link_id

        if session_to_close is not None:
            await self._async_close_session(
                session_to_close,
                WSCloseCode.GOING_AWAY,
                _SHUTDOWN_CLOSE_MESSAGE,
            )

    async def async_unregister_entry(self, entry_id: str) -> None:
        """Remove a config entry and close its active bridge connection."""
        async with self._lock:
            link_id = self._entry_links.pop(entry_id, None)
            if link_id is None:
                return
            self._links.pop(link_id, None)
            session = self._sessions.pop(link_id, None)
            if session is not None:
                self._deactivate_session(session)

        if session is not None:
            await self._async_close_session(
                session,
                WSCloseCode.GOING_AWAY,
                _SHUTDOWN_CLOSE_MESSAGE,
            )

    async def async_shutdown(self) -> None:
        """Close all active sessions during Home Assistant shutdown."""
        async with self._lock:
            sessions = tuple(self._sessions.values())
            self._sessions.clear()
            self._links.clear()
            self._entry_links.clear()
            for session in sessions:
                self._deactivate_session(session)

        await asyncio.gather(
            *(
                self._async_close_session(
                    session,
                    WSCloseCode.GOING_AWAY,
                    _SHUTDOWN_CLOSE_MESSAGE,
                )
                for session in sessions
            )
        )

    async def async_reserve_handshake(self) -> bool:
        """Reserve one bounded unauthenticated handshake slot."""
        async with self._lock:
            if self._pending_handshakes >= MAX_PENDING_HANDSHAKES:
                return False
            self._pending_handshakes += 1
            return True

    async def async_release_handshake(self) -> None:
        """Release a previously reserved handshake slot."""
        async with self._lock:
            if self._pending_handshakes > 0:
                self._pending_handshakes -= 1

    async def async_handle_reserved(
        self,
        websocket: web.WebSocketResponse,
        *,
        client_protocols: tuple[str, ...],
        selected_protocol: str | None,
    ) -> None:
        """Authenticate and run a connection with a reserved handshake slot."""
        session: BridgeSession | None = None
        reservation_released = False

        try:
            async with asyncio.timeout(AUTHENTICATION_TIMEOUT):
                session = await self._async_authenticate(
                    websocket,
                    client_protocols=client_protocols,
                    selected_protocol=selected_protocol,
                )

            await self.async_release_handshake()
            reservation_released = True
            try:
                await self._async_run_session(session)
            except Exception as error:
                self._raise_normalized_session_error(error)
        except _PeerClosed:
            await _async_close(
                websocket,
                WSCloseCode.GOING_AWAY,
                _PEER_CLOSE_MESSAGE,
            )
        except ProtocolError, TimeoutError:
            await _async_close(
                websocket,
                WSCloseCode.POLICY_VIOLATION,
                _POLICY_CLOSE_MESSAGE,
            )
        except ConnectionError:
            await _async_close(
                websocket,
                WSCloseCode.GOING_AWAY,
                _PEER_CLOSE_MESSAGE,
            )
        finally:
            if not reservation_released:
                await self.async_release_handshake()
            if session is not None:
                await self._async_release_session(session)

    async def async_is_ready(self, link_id: str) -> bool:
        """Return whether a link currently has a ready authenticated session."""
        async with self._lock:
            session = self._sessions.get(link_id)
            return session is not None and session.ready

    async def async_active_session_count(self) -> int:
        """Return the number of authenticated sessions."""
        async with self._lock:
            return len(self._sessions)

    async def _async_authenticate(
        self,
        websocket: web.WebSocketResponse,
        *,
        client_protocols: tuple[str, ...],
        selected_protocol: str | None,
    ) -> BridgeSession:
        """Perform mutual authentication and claim the configured link."""
        async with asyncio.timeout(FIRST_MESSAGE_TIMEOUT):
            hello_document = await _async_receive_document(websocket)

        selection: ProtocolSelection | None = None
        if selected_protocol is None:
            if client_protocols:
                raise ProtocolCompatibilityError("incompatible protocol")
            hello = parse_hello(hello_document)
        else:
            if (
                select_websocket_subprotocol(
                    client_protocols,
                    SUPPORTED_WEBSOCKET_SUBPROTOCOLS,
                )
                != selected_protocol
            ):
                raise ProtocolCompatibilityError("incompatible protocol")
            hello = parse_v2_hello(hello_document)
            if (
                hello.client_protocols != client_protocols
                or hello.selected_protocol != selected_protocol
            ):
                raise ProtocolAuthenticationError("protocol authentication failed")

        async with self._lock:
            link = self._links.get(hello.link_id)
        if link is None:
            raise ProtocolAuthenticationError("protocol authentication failed")
        pairing_key = link.pairing_key

        if selected_protocol is None:
            context = make_handshake_context(hello, generate_nonce())
            await _async_send_document(
                websocket,
                build_challenge(pairing_key, context),
            )
            verify_authenticate(
                pairing_key,
                context,
                await _async_receive_document(websocket),
            )
            session_key = derive_session_key(pairing_key, context)
            session_id = derive_session_id(session_key, context)
            ready_document = build_ready(session_key, context)
        else:
            context_v2 = make_v2_handshake_context(
                hello,
                generate_nonce(),
                server_protocols=SUPPORTED_WEBSOCKET_SUBPROTOCOLS,
                server_features=SUPPORTED_V2_FEATURES,
            )
            await _async_send_document(
                websocket,
                build_v2_challenge(pairing_key, context_v2),
            )
            verify_v2_authenticate(
                pairing_key,
                context_v2,
                await _async_receive_document(websocket),
            )
            session_key = derive_v2_session_key(pairing_key, context_v2)
            session_id = derive_v2_session_id(session_key, context_v2)
            selection = context_v2.selection
            ready_document = build_v2_ready(session_key, context_v2)

        session = BridgeSession(
            entry_id=link.entry_id,
            link_id=link.link_id,
            destination_id=hello.destination_id,
            session_id=session_id,
            websocket=websocket,
            session_key=session_key,
            selection=selection,
        )

        async with self._lock:
            if session.link_id in self._sessions:
                raise ProtocolError("protocol authentication failed")
            if self._links.get(session.link_id) != link:
                raise ProtocolError("protocol authentication failed")
            self._sessions[session.link_id] = session

        try:
            await _async_send_document(websocket, ready_document)
        except BaseException:
            await self._async_release_session(session)
            raise
        return session


__all__ = [
    "AUTHENTICATION_TIMEOUT",
    "BRIDGE_WEBSOCKET_PATH",
    "FIRST_MESSAGE_TIMEOUT",
    "MAX_BRIDGE_MESSAGE_BYTES",
    "MAX_PENDING_HANDSHAKES",
    "SUPPORTED_V2_FEATURES",
    "BridgeApplication",
    "BridgeApplicationSession",
    "BridgeConfigurationError",
    "BridgeLink",
    "BridgeSession",
    "DomoticzBridgeManager",
    "DomoticzBridgeView",
    "DomoticzControlHandler",
    "_POLICY_CLOSE_MESSAGE",
    "_parse_domoticz_color",
]
