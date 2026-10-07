"""Target adapters and strategies for bridge export reconciliation."""

from __future__ import annotations

import asyncio
import logging
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from homeassistant.core import HomeAssistant

from .bridge_view import _parse_ping
from .catalog_storage import (
    HomeAssistantBinaryCatalogStorage,
    HomeAssistantCatalogStorage,
)
from .core.capabilities import (
    Capability,
    CapabilityKind,
    CompoundCapability,
    SourceIdentity,
)
from .core.catalog import TargetCatalog
from .core.execution import (
    ApplyConfirmation,
    CatalogStorage,
    ExecutionReport,
    ExecutionStatus,
    TargetActionError,
)
from .core.protocol import (
    FEATURE_HA_EXPORT_BINARY_V1,
    FEATURE_HA_EXPORT_NUMERIC_V1,
    MAX_INVENTORY_TARGETS,
    MAX_INVENTORY_UNITS,
    ApplyResult,
    ApplyResultStatus,
    ProtocolError,
    build_apply,
    build_binary_apply,
    generate_request_id,
    parse_apply_result,
    parse_binary_apply_result,
)
from .core.reconciliation import (
    ReconciliationAction,
    ReconciliationActionKind,
    SourceScope,
    TargetBindingError,
    TargetObservation,
    TargetRecord,
    derive_domoticz_target_id,
    plan_reconciliation,
)
from .home_assistant_source import ExportExclusion

if TYPE_CHECKING:
    from .bridge import BridgeApplicationSession

_LOGGER = logging.getLogger(__name__)

APPLY_TIMEOUT = 10.0


def _reconciliation_attr(name: str, default: object) -> object:
    mod = sys.modules.get("custom_components.domoticz_sync.bridge_reconciliation")
    return getattr(mod, name, default) if mod is not None else default


@dataclass(frozen=True)
class _InventoryAdmission:
    """Capacity-safe baseline and session-local blocked identities."""

    capabilities: tuple[Capability | CompoundCapability, ...]
    blocked_sources: frozenset[SourceIdentity]
    blocked_durable_sources: frozenset[SourceIdentity]


class DomoticzSessionTargetAdapter:
    """Apply numeric actions over one authenticated bridge session."""

    def __init__(self, session: BridgeApplicationSession) -> None:
        """Bind the adapter to one sequential application session."""
        self._session = session

    async def async_apply(
        self,
        action: ReconciliationAction,
    ) -> ApplyConfirmation:
        """Send one action and wait for its exact correlated result."""
        request_id = generate_request_id()

        apply_timeout = float(_reconciliation_attr("APPLY_TIMEOUT", APPLY_TIMEOUT))
        async with asyncio.timeout(apply_timeout):
            await self._session.async_send(self._build_apply(request_id, action))
            while True:
                payload = await self._session.async_receive()
                if isinstance(payload, dict) and payload.get("type") == "ping":
                    ping_id = _parse_ping(payload)
                    await self._session.async_send({"id": ping_id, "type": "pong"})
                    continue

                result = self._parse_apply_result(payload)
                if result.request_id != request_id:
                    raise ProtocolError("invalid protocol message")
                if result.status is ApplyResultStatus.REJECTED:
                    raise TargetActionError("target action was rejected")

                if (
                    result.source != action.capability.source
                    or result.target_id is None
                ):
                    raise ProtocolError("invalid protocol message")
                if (
                    action.kind is not ReconciliationActionKind.CREATE
                    and result.target_id != action.target_id
                ):
                    raise ProtocolError("invalid protocol message")
                return ApplyConfirmation(result.target_id, result.source)

    def _build_apply(
        self,
        request_id: str,
        action: ReconciliationAction,
    ) -> dict[str, object]:
        """Build one numeric action request."""
        return build_apply(self._session.selection, request_id, action)

    def _parse_apply_result(self, payload: object) -> ApplyResult:
        """Parse one numeric action result."""
        return parse_apply_result(self._session.selection, payload)


class DomoticzBinarySessionTargetAdapter(DomoticzSessionTargetAdapter):
    """Apply binary actions over one authenticated bridge session."""

    def _build_apply(
        self,
        request_id: str,
        action: ReconciliationAction,
    ) -> dict[str, object]:
        """Build one binary action request."""
        return build_binary_apply(self._session.selection, request_id, action)

    def _parse_apply_result(self, payload: object) -> ApplyResult:
        """Parse one binary action result."""
        return parse_binary_apply_result(self._session.selection, payload)


class _ExportStorageFactory(Protocol):
    """Construct destination-scoped storage through a stable keyword API."""

    def __call__(
        self,
        hass: HomeAssistant,
        *,
        entry_id: str,
        destination_id: str,
    ) -> CatalogStorage:
        """Build storage for one configured destination."""
        raise NotImplementedError


@dataclass(frozen=True)
class _ExportKindStrategy:
    """Bind one negotiated export kind to its transport and storage adapters."""

    kind: CapabilityKind
    feature: str
    adapter_factory: Callable[[BridgeApplicationSession], DomoticzSessionTargetAdapter]
    storage_factory: _ExportStorageFactory


def _numeric_adapter_factory(
    session: BridgeApplicationSession,
) -> DomoticzSessionTargetAdapter:
    """Build the numeric adapter using the current module implementation."""
    return DomoticzSessionTargetAdapter(session)


def _binary_adapter_factory(
    session: BridgeApplicationSession,
) -> DomoticzSessionTargetAdapter:
    """Build the binary adapter using the current module implementation."""
    return DomoticzBinarySessionTargetAdapter(session)


def _numeric_storage_factory(
    hass: HomeAssistant,
    *,
    entry_id: str,
    destination_id: str,
) -> CatalogStorage:
    """Build numeric storage using the current module implementation."""
    mod = sys.modules.get("custom_components.domoticz_sync.bridge_reconciliation")
    cls = getattr(mod, "HomeAssistantCatalogStorage", HomeAssistantCatalogStorage)
    return cls(hass, entry_id=entry_id, destination_id=destination_id)


def _binary_storage_factory(
    hass: HomeAssistant,
    *,
    entry_id: str,
    destination_id: str,
) -> CatalogStorage:
    """Build binary storage using the current module implementation."""
    mod = sys.modules.get("custom_components.domoticz_sync.bridge_reconciliation")
    cls = getattr(
        mod, "HomeAssistantBinaryCatalogStorage", HomeAssistantBinaryCatalogStorage
    )
    return cls(hass, entry_id=entry_id, destination_id=destination_id)


_NUMERIC_EXPORT_STRATEGY = _ExportKindStrategy(
    CapabilityKind.NUMERIC,
    FEATURE_HA_EXPORT_NUMERIC_V1,
    _numeric_adapter_factory,
    _numeric_storage_factory,
)
_BINARY_EXPORT_STRATEGY = _ExportKindStrategy(
    CapabilityKind.BINARY,
    FEATURE_HA_EXPORT_BINARY_V1,
    _binary_adapter_factory,
    _binary_storage_factory,
)

_EXPORT_EXECUTION_STRATEGIES = (
    _NUMERIC_EXPORT_STRATEGY,
    _BINARY_EXPORT_STRATEGY,
)
_ALL_CATALOG_STRATEGIES = (
    _BINARY_EXPORT_STRATEGY,
    _NUMERIC_EXPORT_STRATEGY,
)


def _capability_kinds_for_strategy(
    strategy: _ExportKindStrategy,
) -> frozenset[CapabilityKind]:
    """Return capability kinds stored under one negotiated feature catalog."""
    if strategy.kind is CapabilityKind.NUMERIC:
        return frozenset({CapabilityKind.NUMERIC, CapabilityKind.COMPOUND})
    if strategy.kind is CapabilityKind.BINARY:
        return frozenset({CapabilityKind.BINARY, CapabilityKind.TEXT})
    return frozenset({strategy.kind})


def _negotiated_export_strategies(
    session: BridgeApplicationSession,
) -> tuple[_ExportKindStrategy, ...]:
    """Return negotiated export strategies in stable execution order."""
    return tuple(
        strategy
        for strategy in _EXPORT_EXECUTION_STRATEGIES
        if session.supports(strategy.feature)
    )


def _storage_for_strategy(
    hass: HomeAssistant,
    session: BridgeApplicationSession,
    strategy: _ExportKindStrategy,
) -> CatalogStorage:
    """Build one destination-scoped catalog adapter for a capability kind."""
    return strategy.storage_factory(
        hass,
        entry_id=session.entry_id,
        destination_id=session.destination_id,
    )


def _log_reports(reports: list[ExecutionReport]) -> None:
    """Log aggregate outcomes without exposing source state or identity."""
    committed = sum(
        result.status is ExecutionStatus.COMMITTED
        for report in reports
        for result in report.results
    )
    rejected = sum(
        result.status is ExecutionStatus.TARGET_NOT_CONFIRMED
        for report in reports
        for result in report.results
    )
    _LOGGER.info(
        "Domoticz export reconciliation completed: "
        "%d planned, %d committed, %d rejected",
        sum(len(report.actions) for report in reports),
        committed,
        rejected,
    )


def _ensure_persistence_confirmed(report: ExecutionReport) -> None:
    """Stop before another catalog is touched after an uncertain write."""
    if report.persistence_uncertain:
        _LOGGER.warning(
            "Domoticz export reconciliation stopped because catalog "
            "persistence could not be confirmed"
        )
        raise ProtocolError("export reconciliation is unavailable")


def _report_exclusions(
    reported_exclusions: dict[tuple[str, str], frozenset[ExportExclusion]],
    session: BridgeApplicationSession,
    exclusions: tuple[ExportExclusion, ...],
) -> None:
    """Warn once for each current safe exclusion diagnostic."""
    key = (session.entry_id, session.destination_id)
    current = frozenset(exclusions)
    previous = reported_exclusions.get(key, frozenset())
    for exclusion in sorted(
        current - previous,
        key=lambda item: (item.entity_id, item.reason.value),
    ):
        _LOGGER.warning(
            "Domoticz export skipped directly labelled entity %s: %s",
            exclusion.entity_id,
            exclusion.reason.value,
        )
    reported_exclusions[key] = current


def _admit_inventory_creates(
    scope: SourceScope,
    capabilities: tuple[Capability | CompoundCapability, ...],
    observations: tuple[TargetObservation, ...],
    catalogs: Mapping[CapabilityKind, TargetCatalog],
    included_kinds: frozenset[CapabilityKind],
) -> _InventoryAdmission:
    """Reserve durable recovery first, then admit globally ordered new targets."""
    observations_by_target_id: dict[str, TargetObservation] = {}
    for observation in observations:
        if observation.target_id in observations_by_target_id:
            raise TargetBindingError("duplicate observed target identity")
        observations_by_target_id[observation.target_id] = observation

    reserved_target_ids = set(observations_by_target_id)
    units_used = sum(
        len(observation.units) for observation in observations_by_target_id.values()
    )
    mod = sys.modules.get("custom_components.domoticz_sync.bridge_reconciliation")
    max_targets = getattr(mod, "MAX_INVENTORY_TARGETS", MAX_INVENTORY_TARGETS)
    max_units = getattr(mod, "MAX_INVENTORY_UNITS", MAX_INVENTORY_UNITS)

    if len(reserved_target_ids) > max_targets or units_used > max_units:
        raise TargetBindingError("target inventory capacity is unavailable")

    current_sources = {capability.source for capability in capabilities}
    durable_records = tuple(
        record for catalog in catalogs.values() for record in catalog.records
    )
    recovery_reservations = tuple(
        record
        for record in durable_records
        if (
            observations_by_target_id.get(record.target_id) is None
            or observations_by_target_id[record.target_id].units == ()
        )
    )
    blocked_durable_sources: set[SourceIdentity] = set()
    for record in sorted(
        recovery_reservations,
        key=lambda item: (
            item.capability.source not in current_sources,
            item.capability.source.key,
        ),
    ):
        source = record.capability.source
        target_cost = int(record.target_id not in reserved_target_ids)
        if (
            len(reserved_target_ids) + target_cost > max_targets
            or units_used + 1 > max_units
        ):
            blocked_durable_sources.add(source)
            continue
        reserved_target_ids.add(record.target_id)
        units_used += 1

    create_actions = []
    for strategy in _ALL_CATALOG_STRATEGIES:
        strategy_kinds = _capability_kinds_for_strategy(strategy)
        if not strategy_kinds & included_kinds:
            continue
        current = tuple(
            capability
            for capability in capabilities
            if capability.kind in strategy_kinds
        )
        create_actions.extend(
            action
            for action in plan_reconciliation(
                scope,
                current,
                catalogs[strategy.kind].records,
                observations,
            )
            if action.kind is ReconciliationActionKind.CREATE
        )

    blocked_create_sources: set[SourceIdentity] = set()
    for action in sorted(
        create_actions,
        key=lambda item: item.capability.source.key,
    ):
        source = action.capability.source
        target_id = derive_domoticz_target_id(source)
        target_cost = int(target_id not in reserved_target_ids)
        if (
            len(reserved_target_ids) + target_cost > max_targets
            or units_used + 1 > max_units
        ):
            blocked_create_sources.add(source)
            continue
        reserved_target_ids.add(target_id)
        units_used += 1

    blocked_sources = blocked_durable_sources | blocked_create_sources
    admitted = tuple(
        capability
        for capability in capabilities
        if capability.source not in blocked_sources
    )
    return _InventoryAdmission(
        capabilities=admitted,
        blocked_sources=frozenset(blocked_sources),
        blocked_durable_sources=frozenset(blocked_durable_sources),
    )


def _desired_record(action: ReconciliationAction) -> TargetRecord:
    """Normalize CREATE and existing-target actions to one desired target state."""
    target_id = action.target_id
    if target_id is None:
        target_id = derive_domoticz_target_id(action.capability.source)
    return TargetRecord(
        target_id=target_id,
        capability=action.capability,
        stale=action.stale,
    )


def _suppress_unchanged_rejections(
    kinds: frozenset[CapabilityKind],
    actions: tuple[ReconciliationAction, ...],
    rejected_desired_records: dict[SourceIdentity, TargetRecord],
) -> tuple[ReconciliationAction, ...]:
    """Skip only the same desired state rejected earlier in this session."""
    desired_by_source = {
        action.capability.source: _desired_record(action) for action in actions
    }
    for source, rejected in tuple(rejected_desired_records.items()):
        if rejected.capability.kind not in kinds:
            continue
        if desired_by_source.get(source) != rejected:
            rejected_desired_records.pop(source)

    return tuple(
        action
        for action in actions
        if rejected_desired_records.get(action.capability.source)
        != desired_by_source[action.capability.source]
    )


def _update_rejected_desired_records(
    rejected_desired_records: dict[SourceIdentity, TargetRecord],
    reports: list[ExecutionReport],
) -> None:
    """Remember expected rejections without leaking them across sessions."""
    for report in reports:
        for result in report.results:
            source = result.action.capability.source
            if result.status is ExecutionStatus.TARGET_NOT_CONFIRMED:
                rejected_desired_records[source] = _desired_record(result.action)
            elif result.status is ExecutionStatus.COMMITTED:
                rejected_desired_records.pop(source, None)


def _action_matches_catalog(
    action: ReconciliationAction,
    catalog: TargetCatalog,
) -> bool:
    """Return whether an existing record already represents one live action."""
    if action.kind is ReconciliationActionKind.CREATE:
        return False
    existing = catalog.get(action.capability.source)
    return existing is not None and existing == _desired_record(action)
