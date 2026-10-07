"""Home Assistant export reconciliation for the Domoticz bridge."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.helpers.instance_id import async_get as async_get_instance_id

from .catalog_storage import (
    HomeAssistantBinaryCatalogStorage,
    HomeAssistantCatalogStorage,
)
from .const import CONF_EXPORT_LABEL_ID
from .core.capabilities import (
    Capability,
    CapabilityKind,
    CompoundCapability,
    SourceIdentity,
)
from .core.catalog import CatalogFormatError, TargetCatalog
from .core.execution import (
    CatalogStorage,
    CatalogStorageError,
    ExecutionConflictError,
    ExecutionReport,
    ReconciliationExecutor,
    async_execute_reconciliation,
)
from .core.protocol import (
    FEATURE_DOMOTICZ_INVENTORY_V1,
    FEATURE_HA_EXPORT_CONTINUOUS_V1,
    ProtocolError,
)
from .core.reconciliation import (
    ReconciliationAction,
    ReconciliationActionKind,
    SourceScope,
    TargetBindingError,
    TargetObservation,
    TargetRecord,
    plan_reconciliation,
)
from .home_assistant_source import (
    ExportCollection,
    ExportExclusion,
    ExportLabelNotFoundError,
    async_subscribe_export_changes,
    collect_export_selection,
)
from .reconciliation_adapters import (
    APPLY_TIMEOUT,
    DomoticzBinarySessionTargetAdapter,
    DomoticzSessionTargetAdapter,
    _action_matches_catalog,
    _admit_inventory_creates,
    _capability_kinds_for_strategy,
    _desired_record,
    _ensure_persistence_confirmed,
    _ExportKindStrategy,
    _ExportStorageFactory,
    _InventoryAdmission,
    _log_reports,
    _negotiated_export_strategies,
    _storage_for_strategy,
    _suppress_unchanged_rejections,
    _update_rejected_desired_records,
)
from .reconciliation_inventory import (
    INVENTORY_TIMEOUT,
    MAX_INVENTORY_TARGETS,
    MAX_INVENTORY_UNITS,
    _async_fetch_inventory,
    _async_preload_catalogs,
    _ContinuousDirtySignal,
    _parse_ping,
    _PreloadedCatalogStorage,
)

if TYPE_CHECKING:
    from .bridge import BridgeApplicationSession

_LOGGER = logging.getLogger(__name__)

CONTINUOUS_COALESCE_SECONDS = 0.25
_SOURCE_SYSTEM = "home_assistant"


class HomeAssistantExportApplication:
    """Reconcile negotiated labelled entities when a bridge session connects."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Store the Home Assistant instance used for source collection."""
        self._hass = hass
        self._destination_locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._reported_exclusions: dict[
            tuple[str, str], frozenset[ExportExclusion]
        ] = {}

    async def async_connected(self, session: BridgeApplicationSession) -> None:
        """Run one fail-closed reconciliation for each negotiated capability kind."""
        strategies = _negotiated_export_strategies(session)
        inventory_enabled = session.supports(FEATURE_DOMOTICZ_INVENTORY_V1)
        continuous_enabled = session.supports(FEATURE_HA_EXPORT_CONTINUOUS_V1)
        if continuous_enabled and (not inventory_enabled or not strategies):
            raise ProtocolError("continuous export is unavailable")
        if not strategies:
            return

        key = (session.entry_id, session.destination_id)
        lock = self._destination_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._destination_locks[key] = lock
        async with lock:
            await self._async_connected_locked(
                session,
                strategies=strategies,
                inventory_enabled=inventory_enabled,
                continuous_enabled=continuous_enabled,
            )

    async def _async_connected_locked(
        self,
        session: BridgeApplicationSession,
        *,
        strategies: tuple[_ExportKindStrategy, ...],
        inventory_enabled: bool,
        continuous_enabled: bool,
    ) -> None:
        """Run one complete destination transaction under its application lock."""
        entry = self._hass.config_entries.async_get_entry(session.entry_id)
        if entry is None:
            raise ProtocolError("export reconciliation is unavailable")

        label_id = entry.data.get(CONF_EXPORT_LABEL_ID)
        if not isinstance(label_id, str) or not label_id:
            raise ProtocolError("export reconciliation is unavailable")

        dirty_signal: _ContinuousDirtySignal | None = None
        unsubscribe = None
        rejected_desired_records: dict[SourceIdentity, TargetRecord] = {}
        try:
            instance_id = await async_get_instance_id(self._hass)
            included_kinds = frozenset(
                kind
                for strategy in strategies
                for kind in _capability_kinds_for_strategy(strategy)
            )
            if continuous_enabled:
                dirty_signal = _ContinuousDirtySignal()
                unsubscribe = async_subscribe_export_changes(
                    self._hass,
                    label_id=label_id,
                    on_change=dirty_signal.mark_dirty,
                )
            collection = collect_export_selection(
                self._hass,
                instance_id=instance_id,
                label_id=label_id,
                included_kinds=included_kinds,
            )
            observations: tuple[TargetObservation, ...] | None = None
            staged_storages: dict[CapabilityKind, CatalogStorage] = {}
            catalogs: dict[CapabilityKind, TargetCatalog] = {}
            reconciliation_capabilities = collection.capabilities
            capacity_blocked_sources: set[SourceIdentity] = set()
            active_capacity_blocked_durable_sources: set[SourceIdentity] = set()
            fresh_inventory_required_sources: set[SourceIdentity] = set()
            if inventory_enabled:
                inventory = await _async_fetch_inventory(session)
                observations = tuple(
                    TargetObservation(
                        target.target_id,
                        tuple(unit.unit for unit in target.units),
                    )
                    for target in inventory
                )
                staged_storages, catalogs = await _async_preload_catalogs(
                    self._hass,
                    session,
                    collection.capabilities,
                )
                admission = _admit_inventory_creates(
                    SourceScope(_SOURCE_SYSTEM, instance_id),
                    collection.capabilities,
                    observations,
                    catalogs,
                    included_kinds,
                )
                reconciliation_capabilities = admission.capabilities
                capacity_blocked_sources = set(admission.blocked_sources)
                current_sources = {
                    capability.source for capability in collection.capabilities
                }
                active_capacity_blocked_durable_sources = (
                    set(admission.blocked_durable_sources) & current_sources
                )
                fresh_inventory_required_sources = (
                    set(admission.blocked_durable_sources) - current_sources
                )
            self._report_exclusions(session, collection.exclusions)

            reports: list[ExecutionReport] = []
            for strategy in strategies:
                report = await self._async_reconcile_kind(
                    session,
                    instance_id,
                    reconciliation_capabilities,
                    strategy=strategy,
                    observations=observations,
                    storage=staged_storages.get(strategy.kind),
                )
                _ensure_persistence_confirmed(report)
                reports.append(report)
                catalogs[strategy.kind] = report.catalog

            _update_rejected_desired_records(rejected_desired_records, reports)
            _log_reports(reports)

            if dirty_signal is not None:
                catalog_sources = {
                    record.capability.source
                    for catalog in catalogs.values()
                    for record in catalog.records
                }
                blocked_sources = {
                    capability.source for capability in collection.capabilities
                } - catalog_sources
                blocked_sources.update(capacity_blocked_sources)
                await self._async_run_continuous(
                    session,
                    instance_id=instance_id,
                    label_id=label_id,
                    strategies=strategies,
                    included_kinds=included_kinds,
                    dirty_signal=dirty_signal,
                    blocked_sources=blocked_sources,
                    capacity_blocked_sources=capacity_blocked_sources,
                    active_capacity_blocked_durable_sources=(
                        active_capacity_blocked_durable_sources
                    ),
                    fresh_inventory_required_sources=(fresh_inventory_required_sources),
                    rejected_desired_records=rejected_desired_records,
                )
        except (
            CatalogFormatError,
            CatalogStorageError,
            ExecutionConflictError,
            ExportLabelNotFoundError,
            TargetBindingError,
        ) as error:
            raise ProtocolError("export reconciliation is unavailable") from error
        finally:
            if dirty_signal is not None:
                dirty_signal.deactivate()
            if unsubscribe is not None:
                unsubscribe()

    async def _async_run_continuous(
        self,
        session: BridgeApplicationSession,
        *,
        instance_id: str,
        label_id: str,
        strategies: tuple[_ExportKindStrategy, ...],
        included_kinds: frozenset[CapabilityKind],
        dirty_signal: _ContinuousDirtySignal,
        blocked_sources: set[SourceIdentity],
        capacity_blocked_sources: set[SourceIdentity],
        active_capacity_blocked_durable_sources: set[SourceIdentity],
        fresh_inventory_required_sources: set[SourceIdentity],
        rejected_desired_records: dict[SourceIdentity, TargetRecord],
    ) -> None:
        """Run serialized catalog-owned deltas until this session ends."""
        while True:
            await dirty_signal.event.wait()
            await asyncio.sleep(CONTINUOUS_COALESCE_SECONDS)
            cycle_generation = dirty_signal.generation
            dirty_signal.event.clear()

            reports = await self._async_reconcile_live_snapshot(
                session,
                instance_id=instance_id,
                label_id=label_id,
                strategies=strategies,
                included_kinds=included_kinds,
                blocked_sources=blocked_sources,
                capacity_blocked_sources=capacity_blocked_sources,
                active_capacity_blocked_durable_sources=(
                    active_capacity_blocked_durable_sources
                ),
                fresh_inventory_required_sources=fresh_inventory_required_sources,
                rejected_desired_records=rejected_desired_records,
            )
            _log_reports(reports)

            if dirty_signal.generation != cycle_generation:
                dirty_signal.event.set()

    async def _async_reconcile_live_snapshot(
        self,
        session: BridgeApplicationSession,
        *,
        instance_id: str,
        label_id: str,
        strategies: tuple[_ExportKindStrategy, ...],
        included_kinds: frozenset[CapabilityKind],
        blocked_sources: set[SourceIdentity],
        capacity_blocked_sources: set[SourceIdentity],
        active_capacity_blocked_durable_sources: set[SourceIdentity],
        fresh_inventory_required_sources: set[SourceIdentity],
        rejected_desired_records: dict[SourceIdentity, TargetRecord],
    ) -> list[ExecutionReport]:
        """Collect and apply one jointly preflighted catalog-owned live delta."""
        collection = collect_export_selection(
            self._hass,
            instance_id=instance_id,
            label_id=label_id,
            included_kinds=included_kinds,
        )
        self._report_exclusions(session, collection.exclusions)
        staged_storages, catalogs = await _async_preload_catalogs(
            self._hass,
            session,
            collection.capabilities,
        )

        current_sources = {capability.source for capability in collection.capabilities}
        catalog_sources = {
            record.capability.source
            for catalog in catalogs.values()
            for record in catalog.records
        }
        fresh_inventory_required_sources.update(
            active_capacity_blocked_durable_sources - current_sources
        )
        active_capacity_blocked_durable_sources.intersection_update(current_sources)
        if current_sources & fresh_inventory_required_sources:
            raise ConnectionError("fresh inventory is required")
        blocked_sources.intersection_update(current_sources)
        if current_sources - catalog_sources - blocked_sources:
            raise ConnectionError("fresh inventory is required")

        reports: list[ExecutionReport] = []
        for strategy in strategies:
            report = await self._async_reconcile_live_kind(
                session,
                instance_id,
                collection.capabilities,
                strategy=strategy,
                catalog=catalogs[strategy.kind],
                storage=staged_storages[strategy.kind],
                capacity_blocked_sources=capacity_blocked_sources,
                rejected_desired_records=rejected_desired_records,
            )
            _ensure_persistence_confirmed(report)
            reports.append(report)
        return reports

    async def _async_reconcile_kind(
        self,
        session: BridgeApplicationSession,
        instance_id: str,
        capabilities: tuple[Capability | CompoundCapability, ...],
        *,
        strategy: _ExportKindStrategy,
        observations: tuple[TargetObservation, ...] | None = None,
        storage: CatalogStorage | None = None,
    ) -> ExecutionReport:
        """Reconcile one negotiated kind in its independent target catalog."""
        adapter = strategy.adapter_factory(session)
        if storage is None:
            storage = _storage_for_strategy(self._hass, session, strategy)
        executor = ReconciliationExecutor(adapter, storage)
        scope = SourceScope(_SOURCE_SYSTEM, instance_id)
        current = tuple(
            capability
            for capability in capabilities
            if capability.kind in _capability_kinds_for_strategy(strategy)
        )
        if observations is None:
            return await executor.async_reconcile(scope, current)
        return await executor.async_reconcile(scope, current, observations)

    async def _async_reconcile_live_kind(
        self,
        session: BridgeApplicationSession,
        instance_id: str,
        capabilities: tuple[Capability | CompoundCapability, ...],
        *,
        strategy: _ExportKindStrategy,
        catalog: TargetCatalog,
        storage: CatalogStorage,
        capacity_blocked_sources: set[SourceIdentity],
        rejected_desired_records: dict[SourceIdentity, TargetRecord],
    ) -> ExecutionReport:
        """Apply only changed records that this session's catalogs already own."""
        adapter = strategy.adapter_factory(session)

        scope = SourceScope(_SOURCE_SYSTEM, instance_id)
        current = tuple(
            capability
            for capability in capabilities
            if capability.kind in _capability_kinds_for_strategy(strategy)
        )
        planned = plan_reconciliation(scope, current, catalog.records)
        actions = tuple(
            action
            for action in planned
            if action.kind is not ReconciliationActionKind.CREATE
            and action.capability.source not in capacity_blocked_sources
            and not _action_matches_catalog(action, catalog)
        )
        actions = _suppress_unchanged_rejections(
            _capability_kinds_for_strategy(strategy),
            actions,
            rejected_desired_records,
        )
        report = await async_execute_reconciliation(
            catalog,
            actions,
            adapter,
            storage,
        )
        _update_rejected_desired_records(rejected_desired_records, [report])
        return report

    def _report_exclusions(
        self,
        session: BridgeApplicationSession,
        exclusions: tuple[ExportExclusion, ...],
    ) -> None:
        """Warn once for each current safe exclusion diagnostic."""
        key = (session.entry_id, session.destination_id)
        current = frozenset(exclusions)
        previous = self._reported_exclusions.get(key, frozenset())
        for exclusion in sorted(
            current - previous,
            key=lambda item: (item.entity_id, item.reason.value),
        ):
            _LOGGER.warning(
                "Domoticz export skipped directly labelled entity %s: %s",
                exclusion.entity_id,
                exclusion.reason.value,
            )
        self._reported_exclusions[key] = current


__all__ = [
    "APPLY_TIMEOUT",
    "CONTINUOUS_COALESCE_SECONDS",
    "INVENTORY_TIMEOUT",
    "DomoticzBinarySessionTargetAdapter",
    "DomoticzSessionTargetAdapter",
    "ExportCollection",
    "ExportExclusion",
    "HomeAssistantBinaryCatalogStorage",
    "HomeAssistantCatalogStorage",
    "HomeAssistantExportApplication",
    "ReconciliationAction",
    "ReconciliationActionKind",
    "_ContinuousDirtySignal",
    "_ExportKindStrategy",
    "_ExportStorageFactory",
    "_InventoryAdmission",
    "_PreloadedCatalogStorage",
    "_action_matches_catalog",
    "_admit_inventory_creates",
    "_capability_kinds_for_strategy",
    "_desired_record",
    "_negotiated_export_strategies",
    "_parse_ping",
    "_suppress_unchanged_rejections",
    "_update_rejected_desired_records",
    "async_get_instance_id",
    "collect_export_selection",
    "INVENTORY_TIMEOUT",
    "MAX_INVENTORY_TARGETS",
    "MAX_INVENTORY_UNITS",
    "plan_reconciliation",
]
