"""Bridge session and link structures for the Domoticz companion plugin."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any, Final, Protocol

from aiohttp import WSCloseCode

from .bridge_credentials import BridgeConfigurationError, BridgeLink
from .bridge_types import (
    BridgeSession,
    _async_close,
    _async_receive_document,
    _async_send_document,
    _PeerClosed,
    _raise_normalized_session_error,
    _validate_heartbeat_payload,
)
from .core.protocol import (
    DIRECTION_DOMOTICZ_TO_HA,
    DIRECTION_HA_TO_DOMOTICZ,
    FEATURE_DOMOTICZ_CONTROL_V1,
    FEATURE_HA_EXPORT_BINARY_V1,
    FEATURE_HA_EXPORT_CONTINUOUS_V1,
    FEATURE_HA_EXPORT_NUMERIC_V1,
    MAX_INVENTORY_PAGES,
    PROTOCOL_VERSION,
    ControlResultStatus,
    ProtocolError,
    ProtocolSelection,
    build_application_ready,
    build_control_result,
    generate_nonce,
    parse_application_ready,
    parse_control,
    sign_envelope,
    verify_envelope,
)

MAX_APPLICATION_INBOX_MESSAGES: Final = MAX_INVENTORY_PAGES
MAX_CONTROL_RESULTS: Final = 256
INVENTORY_TIMEOUT: Final = 10.0
HEARTBEAT_INTERVAL: Final = 30.0
HEARTBEAT_RESPONSE_TIMEOUT: Final = 10.0
MAX_CONTROLS_PER_WINDOW: Final = 30
CONTROL_WINDOW_SECONDS: Final = 5.0


class _PayloadSender(Protocol):
    """Manager operation used by the application session facade."""

    async def _async_send_payload(
        self, session: BridgeSession, payload: dict[str, object]
    ) -> None:
        """Send authenticated server envelope."""


class BridgeApplication(Protocol):
    """Application invoked for one ready, authenticated bridge session."""

    async def async_connected(self, session: BridgeApplicationSession) -> None:
        """Use one ready application session until transport ends."""


class BridgeApplicationSession:
    """Narrow signed-payload facade for a ready bridge session."""

    __slots__ = ("_active", "_deactivated", "_inbox", "_manager", "_session")

    def __init__(self, manager: _PayloadSender, session: BridgeSession) -> None:
        """Bind facade to active bridge session."""
        self._manager = manager
        self._session = session
        self._active = True
        self._deactivated = asyncio.Event()
        self._inbox: asyncio.Queue[dict[str, object]] = asyncio.Queue(
            maxsize=MAX_APPLICATION_INBOX_MESSAGES
        )

    @property
    def entry_id(self) -> str:
        return self._session.entry_id

    @property
    def destination_id(self) -> str:
        return self._session.destination_id

    @property
    def selection(self) -> ProtocolSelection:
        """Return authenticated protocol selection."""
        if (selection := self._session.selection) is None:
            raise ProtocolError("application session is unavailable")
        return selection

    def supports(self, feature: str) -> bool:
        """Return whether session negotiated optional feature."""
        return self.selection.supports(feature)

    async def async_send(self, payload: dict[str, object]) -> None:
        """Send one signed application payload."""
        self._ensure_active()
        await self._manager._async_send_payload(self._session, payload)

    async def async_receive(self) -> dict[str, object]:
        """Receive one signed application payload."""
        self._ensure_active()
        payload_task = asyncio.create_task(self._inbox.get())
        deactivation_task = asyncio.create_task(self._deactivated.wait())
        try:
            await asyncio.wait(
                (payload_task, deactivation_task),
                return_when=asyncio.FIRST_COMPLETED,
            )
            self._ensure_active()
            return payload_task.result()
        finally:
            payload_task.cancel()
            deactivation_task.cancel()
            await asyncio.gather(
                payload_task, deactivation_task, return_exceptions=True
            )

    def _deliver(self, payload: dict[str, object]) -> None:
        """Route payload into bounded inbox."""
        self._ensure_active()
        try:
            self._inbox.put_nowait(payload)
        except asyncio.QueueFull:
            raise ProtocolError("application session is unavailable") from None

    def _deactivate(self) -> None:
        """Prevent application traffic after detachment."""
        if not self._active:
            return
        self._active = False
        self._deactivated.set()
        while not self._inbox.empty():
            self._inbox.get_nowait()

    def _ensure_active(self) -> None:
        """Reject use after session detaches."""
        if not self._active:
            raise ProtocolError("application session is no longer active")


class DomoticzSessionRunner:
    """Session execution and transport loop for bridge sessions."""

    _application: BridgeApplication | None
    _lock: asyncio.Lock
    _sessions: dict[str, BridgeSession]

    _async_handle_control_request: Callable[
        [BridgeSession, Any], Awaitable[dict[str, object]]
    ]

    async def _async_run_session(self, session: BridgeSession) -> None:
        """Complete application startup and keep link alive."""
        if session.selection is None:
            await self._async_run_legacy_session(session)
        else:
            await self._async_run_v2_session(session)

    async def _async_run_legacy_session(self, session: BridgeSession) -> None:
        """Preserve v1 inventory, ready, and heartbeat behavior."""
        async with asyncio.timeout(INVENTORY_TIMEOUT):
            inventory = await self._async_receive_payload(session)
        if inventory != {"targets": [], "type": "inventory"}:
            raise ProtocolError("invalid protocol message")

        await self._async_send_payload(session, {"type": "ready"})
        await self._async_mark_ready(session)
        await self._async_run_heartbeat(session)

    async def _async_run_v2_session(self, session: BridgeSession) -> None:
        """Exchange readiness and run v2 behavior."""
        selection = session.selection
        assert selection is not None

        async with asyncio.timeout(INVENTORY_TIMEOUT):
            parse_application_ready(
                selection, await self._async_receive_payload(session)
            )
        await self._async_send_payload(session, build_application_ready(selection))
        await self._async_mark_ready(session)

        if (
            selection.supports(FEATURE_HA_EXPORT_CONTINUOUS_V1)
            and self._application is None
        ):
            raise ProtocolError("application session is unavailable")
        if self._application is not None and any(
            selection.supports(f)
            for f in (
                FEATURE_HA_EXPORT_NUMERIC_V1,
                FEATURE_HA_EXPORT_BINARY_V1,
                FEATURE_HA_EXPORT_CONTINUOUS_V1,
            )
        ):
            await self._async_run_application(session)
            return

        await self._async_run_heartbeat(session, None)

    async def _async_run_application(self, session: BridgeSession) -> None:
        """Run application task beside socket reader."""
        application = self._application
        assert application is not None
        app_sess = BridgeApplicationSession(self, session)
        session.application_session = app_sess
        app_task = asyncio.create_task(application.async_connected(app_sess))
        session.application_task = app_task
        reader_task = asyncio.create_task(self._async_run_heartbeat(session, app_sess))
        primary_error: BaseException | None = None
        try:
            done, _ = await asyncio.wait(
                (app_task, reader_task), return_when=asyncio.FIRST_COMPLETED
            )
            if app_task in done:
                try:
                    await app_task
                except (asyncio.CancelledError, Exception) as error:
                    if isinstance(error, asyncio.CancelledError) and not session.ready:
                        try:
                            await reader_task
                        except (asyncio.CancelledError, Exception) as r_err:
                            primary_error = r_err
                    else:
                        primary_error = error
                else:
                    app_sess._deactivate()
                    try:
                        await reader_task
                    except (asyncio.CancelledError, Exception) as error:
                        primary_error = error
            else:
                try:
                    await reader_task
                except (asyncio.CancelledError, Exception) as error:
                    primary_error = error
        except (asyncio.CancelledError, Exception) as error:
            primary_error = error
        finally:
            app_sess._deactivate()
            for t in (app_task, reader_task):
                if not t.done():
                    t.cancel()
            app_res, reader_res = await asyncio.gather(
                app_task, reader_task, return_exceptions=True
            )
            if session.application_session is app_sess:
                session.application_session = None
            if session.application_task is app_task:
                session.application_task = None

        for res in (app_res, reader_res):
            if isinstance(res, BaseException) and not isinstance(
                res, asyncio.CancelledError
            ):
                self._raise_normalized_session_error(res)
        if primary_error is not None:
            if isinstance(primary_error, asyncio.CancelledError) and not session.ready:
                return
            self._raise_normalized_session_error(primary_error)

    async def _async_run_heartbeat(
        self,
        session: BridgeSession,
        application_session: BridgeApplicationSession | None = None,
    ) -> None:
        """Own reads, heartbeats, and dispatch."""
        pending_ping_id: str | None = None
        pending_ping_deadline: float | None = None
        loop = asyncio.get_running_loop()
        while True:
            timeout = (
                max(0.0, pending_ping_deadline - loop.time())
                if pending_ping_deadline is not None
                else HEARTBEAT_INTERVAL
            )
            try:
                async with asyncio.timeout(timeout):
                    payload = await self._async_receive_payload(session)
            except TimeoutError:
                if pending_ping_id is not None:
                    raise _PeerClosed from None
                ping_id = generate_nonce()
                await self._async_send_payload(session, {"id": ping_id, "type": "ping"})
                pending_ping_id = ping_id
                pending_ping_deadline = loop.time() + HEARTBEAT_RESPONSE_TIMEOUT
                continue

            if not isinstance(payload, dict):
                raise ProtocolError("invalid protocol message")
            message_type = payload.get("type")
            if message_type == "ping":
                ping_id = _validate_heartbeat_payload(payload)
                await self._async_send_payload(session, {"id": ping_id, "type": "pong"})
                continue

            if message_type == "control_request":
                if session.selection is None or not session.selection.supports(
                    FEATURE_DOMOTICZ_CONTROL_V1
                ):
                    raise ProtocolError("invalid protocol message")
                try:
                    request = parse_control(session.selection, payload)
                    cached = session.control_results.get(request.request_id)
                    if cached is not None:
                        cached_req, result = cached
                        if request != cached_req:
                            raise ProtocolError("invalid protocol message")
                    else:
                        in_flight = session.in_flight_controls.get(request.request_id)
                        if in_flight is not None:
                            in_flight_req, fut = in_flight
                            if request != in_flight_req:
                                raise ProtocolError("invalid protocol message")
                            result = await fut
                        else:
                            now = time.monotonic()
                            session.control_timestamps = [
                                ts
                                for ts in session.control_timestamps
                                if now - ts < CONTROL_WINDOW_SECONDS
                            ]
                            if (
                                len(session.control_timestamps)
                                >= MAX_CONTROLS_PER_WINDOW
                            ):
                                result = build_control_result(
                                    session.selection,
                                    request.request_id,
                                    ControlResultStatus.REJECTED,
                                    error="rate limit exceeded",
                                )
                            else:
                                session.control_timestamps.append(now)
                                fut = loop.create_future()
                                session.in_flight_controls[request.request_id] = (
                                    request,
                                    fut,
                                )
                                try:
                                    result = await self._async_handle_control_request(
                                        session, request
                                    )
                                    fut.set_result(result)
                                except BaseException as exc:
                                    if not fut.done():
                                        fut.set_exception(exc)
                                    raise
                                finally:
                                    session.in_flight_controls.pop(
                                        request.request_id, None
                                    )

                                if len(session.control_results) >= MAX_CONTROL_RESULTS:
                                    session.control_results.pop(
                                        next(iter(session.control_results))
                                    )
                                session.control_results[request.request_id] = (
                                    request,
                                    result,
                                )
                except Exception:
                    raise ProtocolError("invalid protocol message") from None
                await self._async_send_payload(session, result)
                continue

            if message_type == "pong":
                pong_id = _validate_heartbeat_payload(payload)
                if pending_ping_id is None or pong_id != pending_ping_id:
                    raise ProtocolError("invalid protocol message")
                pending_ping_id = None
                pending_ping_deadline = None
                continue

            if application_session is None:
                raise ProtocolError("invalid protocol message")
            application_session._deliver(payload)

    async def _async_receive_payload(self, session: BridgeSession) -> dict[str, object]:
        """Receive authenticated client envelope."""
        version = (
            session.selection.version
            if session.selection is not None
            else PROTOCOL_VERSION
        )
        verified = verify_envelope(
            session.session_key,
            await _async_receive_document(session.websocket),
            protocol_version=version,
            expected_direction=DIRECTION_DOMOTICZ_TO_HA,
            expected_session_id=session.session_id,
            last_sequence=session.client_sequence,
        )
        session.client_sequence = verified.sequence
        return verified.payload

    async def _async_send_payload(
        self, session: BridgeSession, payload: dict[str, object]
    ) -> None:
        """Send authenticated server envelope."""
        async with session.send_lock:
            async with self._lock:
                if self._sessions.get(session.link_id) is not session:
                    raise ProtocolError("application session is no longer active")
            sequence = session.server_sequence + 1
            version = (
                session.selection.version
                if session.selection is not None
                else PROTOCOL_VERSION
            )
            document = sign_envelope(
                session.session_key,
                protocol_version=version,
                direction=DIRECTION_HA_TO_DOMOTICZ,
                session_id=session.session_id,
                sequence=sequence,
                payload=payload,
            )
            await _async_send_document(session.websocket, document)
            session.server_sequence = sequence

    @staticmethod
    async def _async_close_session(
        session: BridgeSession, code: WSCloseCode, message: bytes
    ) -> None:
        await _async_close(session.websocket, code, message)

    async def _async_release_session(self, session: BridgeSession) -> None:
        async with self._lock:
            self._deactivate_session(session)
            if self._sessions.get(session.link_id) is session:
                self._sessions.pop(session.link_id)

    async def _async_mark_ready(self, session: BridgeSession) -> None:
        async with self._lock:
            if self._sessions.get(session.link_id) is not session:
                raise _PeerClosed
            session.ready = True

    @staticmethod
    def _deactivate_session(session: BridgeSession) -> None:
        session.ready = False
        if (app_sess := session.application_session) is not None:
            app_sess._deactivate()
        if (app_task := session.application_task) is not None and not app_task.done():
            app_task.cancel()

    _raise_normalized_session_error = staticmethod(_raise_normalized_session_error)


__all__ = [
    "BridgeApplication",
    "BridgeApplicationSession",
    "BridgeConfigurationError",
    "BridgeLink",
    "BridgeSession",
    "DomoticzSessionRunner",
]
