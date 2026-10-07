"""Inventory structures and storage helpers for bridge export reconciliation."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant

from .bridge_view import _parse_ping
from .core.capabilities import (
    Capability,
    CapabilityKind,
    CompoundCapability,
)
from .core.catalog import TargetCatalog, catalog_from_document
from .core.execution import CatalogStorage, CatalogStorageError
from .core.protocol import (
    INVENTORY_TIMEOUT_SECONDS,
    MAX_INVENTORY_PAGES,
    MAX_INVENTORY_TARGETS,
    MAX_INVENTORY_UNITS,
    InventoryResult,
    InventoryTarget,
    ProtocolFormatError,
    assemble_inventory_results,
    build_inventory_request,
    generate_request_id,
    parse_inventory_result,
)
from .core.reconciliation import validate_deterministic_target_ownership
from .reconciliation_adapters import (
    _ALL_CATALOG_STRATEGIES,
    _storage_for_strategy,
)

if TYPE_CHECKING:
    from .bridge import BridgeApplicationSession

INVENTORY_TIMEOUT = float(INVENTORY_TIMEOUT_SECONDS)


def _reconciliation_attr(name: str, default: Any) -> Any:
    mod = sys.modules.get("custom_components.domoticz_sync.bridge_reconciliation")
    return getattr(mod, name, default) if mod is not None else default


class _ContinuousDirtySignal:
    """Track value-free changes without retaining event payload data."""

    def __init__(self) -> None:
        """Initialize one session-local dirty generation."""
        self.event = asyncio.Event()
        self.generation = 0
        self._active = True

    def mark_dirty(self) -> None:
        """Record a change while the owning application session is active."""
        if not self._active:
            return
        self.generation += 1
        self.event.set()

    def deactivate(self) -> None:
        """Make already queued callbacks inert when the session ends."""
        self._active = False


class _PreloadedCatalogStorage:
    """Reuse one catalog document loaded during inventory preflight."""

    def __init__(
        self,
        storage: CatalogStorage,
        document: Mapping[str, object] | None,
    ) -> None:
        """Keep the delegate and its already validated load result."""
        self._storage = storage
        self._document = document
        self._loaded = False

    async def async_load(self) -> Mapping[str, object] | None:
        """Return the preflight document exactly once to its executor."""
        if self._loaded:
            raise CatalogStorageError("target catalog storage is unavailable")
        self._loaded = True
        return self._document

    async def async_save(self, document: Mapping[str, object]) -> None:
        """Delegate atomic persistence after inventory-aware execution."""
        await self._storage.async_save(document)


async def _async_fetch_inventory(
    session: BridgeApplicationSession,
) -> tuple[InventoryTarget, ...]:
    """Request and fully stage one bounded inventory before reconciliation."""
    request_id = generate_request_id()
    pages: list[InventoryResult] = []
    target_count = 0
    unit_count = 0
    previous_target_id: str | None = None

    inv_timeout = _reconciliation_attr("INVENTORY_TIMEOUT", INVENTORY_TIMEOUT)
    max_targets = _reconciliation_attr("MAX_INVENTORY_TARGETS", MAX_INVENTORY_TARGETS)
    max_units = _reconciliation_attr("MAX_INVENTORY_UNITS", MAX_INVENTORY_UNITS)

    async with asyncio.timeout(inv_timeout):
        await session.async_send(build_inventory_request(session.selection, request_id))
        while True:
            payload = await session.async_receive()
            if isinstance(payload, dict) and payload.get("type") == "ping":
                ping_id = _parse_ping(payload)
                await session.async_send({"id": ping_id, "type": "pong"})
                continue

            result = parse_inventory_result(session.selection, payload)
            expected_page = len(pages) + 1
            if (
                expected_page > MAX_INVENTORY_PAGES
                or result.request_id != request_id
                or result.page != expected_page
            ):
                raise ProtocolFormatError("invalid protocol message")

            for target in result.targets:
                if (
                    previous_target_id is not None
                    and target.target_id <= previous_target_id
                ):
                    raise ProtocolFormatError("invalid protocol message")
                previous_target_id = target.target_id
                target_count += 1
                unit_count += len(target.units)
                if target_count > max_targets or unit_count > max_units:
                    raise ProtocolFormatError("invalid protocol message")

            pages.append(result)
            if result.complete:
                return assemble_inventory_results(
                    session.selection,
                    request_id,
                    pages,
                )


async def _async_preload_catalogs(
    hass: HomeAssistant,
    session: BridgeApplicationSession,
    capabilities: tuple[Capability | CompoundCapability, ...],
) -> tuple[
    dict[CapabilityKind, CatalogStorage],
    dict[CapabilityKind, TargetCatalog],
]:
    """Load and jointly validate all catalogs before the first target write."""
    storages = tuple(
        _storage_for_strategy(hass, session, strategy)
        for strategy in _ALL_CATALOG_STRATEGIES
    )
    documents = await asyncio.gather(*(storage.async_load() for storage in storages))
    catalogs = tuple(
        TargetCatalog() if document is None else catalog_from_document(document)
        for document in documents
    )
    validate_deterministic_target_ownership(
        capabilities,
        (record for catalog in catalogs for record in catalog.records),
    )
    return (
        {
            strategy.kind: _PreloadedCatalogStorage(storage, document)
            for strategy, storage, document in zip(
                _ALL_CATALOG_STRATEGIES,
                storages,
                documents,
                strict=True,
            )
        },
        {
            strategy.kind: catalog
            for strategy, catalog in zip(
                _ALL_CATALOG_STRATEGIES,
                catalogs,
                strict=True,
            )
        },
    )
