"""Read labelled Home Assistant entities into the neutral capability model."""

from __future__ import annotations

from collections.abc import Callable, Collection
from dataclasses import dataclass

from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    callback,
)
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import label_registry as lr
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.instance_id import async_get as async_get_instance_id

from .const import CONTROLLABLE_EXPORT_DOMAINS, EXPORT_LABEL_NAME
from .core import (
    Capability,
    CapabilityKind,
    CompoundCapability,
)
from .export_label import async_get_export_label_id
from .provenance import is_domoticz_mirror
from .source_policy import (
    ExportExclusionReason,
    _capability_from_entry,
    _group_temperature_humidity_capabilities,
)

_SUPPORTED_EXPORT_DOMAINS = frozenset(
    {"binary_sensor", "sensor", *CONTROLLABLE_EXPORT_DOMAINS}
)


class ExportLabelNotFoundError(LookupError):
    """Raised when the configured Home Assistant export label was deleted."""


@dataclass(frozen=True, slots=True)
class ExportExclusion:
    """One actionable exclusion without source state or attribute data."""

    entity_id: str
    reason: ExportExclusionReason


@dataclass(frozen=True, slots=True)
class ExportCollection:
    """Exportable capabilities and safe diagnostics for one label snapshot."""

    capabilities: tuple[Capability | CompoundCapability, ...]
    exclusions: tuple[ExportExclusion, ...]


@callback
def async_subscribe_export_changes(
    hass: HomeAssistant,
    *,
    label_id: str,
    on_change: Callable[[], None],
) -> CALLBACK_TYPE:
    """Signal when the authoritative directly labelled export may have changed."""
    label_registry = lr.async_get(hass)
    if (
        not isinstance(label_id, str)
        or not label_id
        or label_registry.async_get_label(label_id) is None
    ):
        raise ExportLabelNotFoundError(
            f"Home Assistant export label {label_id!r} does not exist"
        )

    entity_registry = er.async_get(hass)
    active = True
    direct_entity_ids: frozenset[str] = frozenset()
    state_entity_ids: frozenset[str] = frozenset()

    @callback
    def _noop() -> None:
        """Provide an idempotent placeholder listener."""

    remove_state_listener: CALLBACK_TYPE = _noop
    remove_entity_registry_listener: CALLBACK_TYPE = _noop
    remove_label_registry_listener: CALLBACK_TYPE = _noop

    @callback
    def _async_state_changed(event: Event[EventStateChangedData]) -> None:
        """Turn selected state or attribute changes into a value-free signal."""
        if active and event.data["entity_id"] in state_entity_ids:
            on_change()

    @callback
    def _async_replace_state_listener(*, label_exists: bool = True) -> None:
        """Atomically follow the current direct label membership and entity IDs."""
        nonlocal direct_entity_ids, remove_state_listener, state_entity_ids

        entries = (
            er.async_entries_for_label(entity_registry, label_id)
            if label_exists
            else ()
        )
        new_direct_entity_ids = frozenset(entry.entity_id for entry in entries)
        new_state_entity_ids = frozenset(
            entry.entity_id
            for entry in entries
            if entry.domain in _SUPPORTED_EXPORT_DOMAINS
        )

        direct_entity_ids = new_direct_entity_ids
        if new_state_entity_ids == state_entity_ids:
            return

        old_remove_state_listener = remove_state_listener
        state_entity_ids = new_state_entity_ids
        remove_state_listener = async_track_state_change_event(
            hass,
            sorted(state_entity_ids),
            _async_state_changed,
        )
        old_remove_state_listener()

    @callback
    def _async_entity_registry_event_filter(
        event_data: er.EventEntityRegistryUpdatedData,
    ) -> bool:
        """Admit only previous or current direct members of the export label."""
        if not active:
            return False
        entity_id = event_data["entity_id"]
        if (
            entity_id in direct_entity_ids
            or event_data.get("old_entity_id") in direct_entity_ids
        ):
            return True
        entry = entity_registry.async_get(entity_id)
        return entry is not None and label_id in entry.labels

    @callback
    def _async_entity_registry_changed(
        _event: Event[er.EventEntityRegistryUpdatedData],
    ) -> None:
        """Refresh dynamic state routing before reporting registry metadata."""
        if not active:
            return
        _async_replace_state_listener()
        on_change()

    @callback
    def _async_label_registry_event_filter(
        event_data: lr.EventLabelRegistryUpdatedData,
    ) -> bool:
        """Admit only lifecycle events for the configured stable label ID."""
        return active and event_data["label_id"] == label_id

    @callback
    def _async_label_registry_changed(
        event: Event[lr.EventLabelRegistryUpdatedData],
    ) -> None:
        """Fail closed on deletion while treating a label rename as metadata."""
        if not active or event.data["action"] != "remove":
            return
        _async_replace_state_listener(label_exists=False)
        on_change()

    _async_replace_state_listener()
    remove_entity_registry_listener = hass.bus.async_listen(
        er.EVENT_ENTITY_REGISTRY_UPDATED,
        _async_entity_registry_changed,
        event_filter=_async_entity_registry_event_filter,
    )
    remove_label_registry_listener = hass.bus.async_listen(
        lr.EVENT_LABEL_REGISTRY_UPDATED,
        _async_label_registry_changed,
        event_filter=_async_label_registry_event_filter,
    )

    @callback
    def _async_unsubscribe() -> None:
        """Remove every listener once and make already queued jobs inert."""
        nonlocal active
        if not active:
            return
        active = False
        remove_state_listener()
        remove_entity_registry_listener()
        remove_label_registry_listener()

    return _async_unsubscribe


async def async_collect_export_capabilities(
    hass: HomeAssistant,
    *,
    label_id: str | None = None,
) -> list[Capability]:
    """Collect capabilities using Home Assistant's stable instance ID."""
    collection = collect_export_selection(
        hass,
        instance_id=await async_get_instance_id(hass),
        label_id=label_id,
    )
    return list(collection.capabilities)


@callback
def collect_export_capabilities(
    hass: HomeAssistant,
    *,
    instance_id: str,
    label_id: str | None = None,
) -> list[Capability]:
    """Collect labelled numeric and binary entities without side effects."""
    return list(
        collect_export_selection(
            hass,
            instance_id=instance_id,
            label_id=label_id,
        ).capabilities
    )


@callback
def collect_export_selection(
    hass: HomeAssistant,
    *,
    instance_id: str,
    label_id: str | None = None,
    included_kinds: Collection[CapabilityKind] | None = None,
) -> ExportCollection:
    """Collect labelled entities and explain every direct exclusion."""
    if label_id is None:
        label_id = async_get_export_label_id(hass)
    if label_id is None:
        raise ExportLabelNotFoundError(
            f"Home Assistant export label {EXPORT_LABEL_NAME!r} does not exist"
        )
    if lr.async_get(hass).async_get_label(label_id) is None:
        raise ExportLabelNotFoundError(
            f"Home Assistant export label {label_id!r} does not exist"
        )

    entries = sorted(
        er.async_entries_for_label(er.async_get(hass), label_id),
        key=lambda entry: entry.id,
    )

    if included_kinds is None:
        included_kinds = frozenset(CapabilityKind)

    capabilities: list[Capability | CompoundCapability] = []
    exclusions: list[ExportExclusion] = []
    for entry in entries:
        if entry.disabled:
            exclusions.append(
                ExportExclusion(entry.entity_id, ExportExclusionReason.DISABLED)
            )
            continue
        state = hass.states.get(entry.entity_id)
        attributes = state.attributes if state is not None else {}
        if is_domoticz_mirror(platform=entry.platform, attributes=attributes):
            exclusions.append(
                ExportExclusion(
                    entry.entity_id,
                    ExportExclusionReason.DOMOTICZ_MIRROR,
                )
            )
            continue

        if entry.domain not in _SUPPORTED_EXPORT_DOMAINS:
            exclusions.append(
                ExportExclusion(
                    entry.entity_id,
                    ExportExclusionReason.UNSUPPORTED_DOMAIN,
                )
            )
            continue

        capability, reason = _capability_from_entry(
            hass,
            entry,
            state,
            instance_id=instance_id,
        )
        if reason is not None:
            exclusion_reason = (
                reason
                if isinstance(reason, ExportExclusionReason)
                else ExportExclusionReason(reason)
            )
            exclusions.append(ExportExclusion(entry.entity_id, exclusion_reason))
            continue
        assert capability is not None
        if capability.kind not in included_kinds:
            exclusions.append(
                ExportExclusion(
                    entry.entity_id,
                    ExportExclusionReason.CAPABILITY_KIND_NOT_ENABLED,
                )
            )
            continue
        capabilities.append(capability)

    if CapabilityKind.COMPOUND in included_kinds:
        capabilities = _group_temperature_humidity_capabilities(
            hass,
            entries,
            capabilities,
            instance_id=instance_id,
        )

    return ExportCollection(tuple(capabilities), tuple(exclusions))
