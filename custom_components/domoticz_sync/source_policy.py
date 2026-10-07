"""Capability conversion and classification policies for Home Assistant entities."""

from __future__ import annotations

from enum import StrEnum
from math import isfinite
from typing import Any

from homeassistant.const import (
    LIGHT_LUX,
    PERCENTAGE,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfPrecipitationDepth,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
    UnitOfVolume,
    UnitOfVolumetricFlux,
)
from homeassistant.core import State
from homeassistant.helpers import entity_registry as er

from .const import CONTROLLABLE_EXPORT_DOMAINS
from .core import Availability, Capability, CapabilityKind, SourceIdentity

_BINARY_SENSOR_DOMAIN = "binary_sensor"
_NON_NUMERIC_SENSOR_DEVICE_CLASSES = {"date", "enum", "timestamp", "uptime"}

_UNIT_MAP = {
    UnitOfTemperature.CELSIUS: "celsius",
    UnitOfTemperature.FAHRENHEIT: "fahrenheit",
    PERCENTAGE: "percent",
    UnitOfPressure.HPA: "hpa",
    UnitOfPressure.BAR: "bar",
    LIGHT_LUX: "lux",
    UnitOfElectricPotential.VOLT: "volt",
    UnitOfElectricCurrent.AMPERE: "A",
    UnitOfFrequency.HERTZ: "hz",
    UnitOfPower.WATT: "watt",
    UnitOfEnergy.KILO_WATT_HOUR: "kwh",
    UnitOfVolume.CUBIC_METERS: "m3",
    UnitOfVolume.LITERS: "l",
    UnitOfPrecipitationDepth.MILLIMETERS: "mm",
    UnitOfVolumetricFlux.MILLIMETERS_PER_HOUR: "mm_per_hour",
    UnitOfSpeed.METERS_PER_SECOND: "meter_per_second",
}


class ExportExclusionReason(StrEnum):
    """Fixed, log-safe reason why one directly labelled entity was excluded."""

    DISABLED = "entity is disabled"
    UNSUPPORTED_DOMAIN = "entity domain is not supported"
    DOMOTICZ_MIRROR = "Domoticz-origin entity cannot be exported back"
    NON_NUMERIC_DEVICE_CLASS = "sensor device class is not numeric"
    INVALID_NUMERIC_STATE = "sensor state is not a finite number"
    MISSING_NUMERIC_METADATA = "unknown or unavailable sensor lacks numeric metadata"
    INVALID_BINARY_STATE = "binary sensor state is invalid"
    MISSING_SELECTOR_OPTIONS = "selector lacks options metadata"
    CAPABILITY_KIND_NOT_ENABLED = "entity type is not enabled for export"


def _selector_capability(
    source: SourceIdentity,
    name: str,
    state: State | None,
) -> tuple[Capability | None, ExportExclusionReason | None]:
    """Convert a selector entity (select or input_select)."""
    attributes = state.attributes if state is not None else {}
    raw_options = attributes.get("options")
    if not isinstance(raw_options, (list, tuple)) or not raw_options:
        return None, ExportExclusionReason.MISSING_SELECTOR_OPTIONS

    cleaned_options: list[str] = []
    for opt in raw_options:
        if not isinstance(opt, str) or not opt.strip():
            continue
        sanitized = opt.replace("|", "/").strip()
        if sanitized and sanitized not in cleaned_options:
            cleaned_options.append(sanitized)

    if not cleaned_options:
        return None, ExportExclusionReason.MISSING_SELECTOR_OPTIONS

    options = tuple(cleaned_options[:30])

    if state is None or state.state == STATE_UNAVAILABLE:
        availability = Availability.UNAVAILABLE
        value = None
    elif state.state == STATE_UNKNOWN:
        availability = Availability.UNKNOWN
        value = None
    else:
        current_state = state.state.replace("|", "/").strip()
        if current_state not in options:
            options = (current_state, *options)[:30]
        availability = Availability.AVAILABLE
        value = current_state

    return (
        Capability(
            source=source,
            kind=CapabilityKind.TEXT,
            name=name,
            value=value,
            availability=availability,
            semantic="selector",
            options=options,
        ),
        None,
    )


def _binary_capability(
    source: SourceIdentity,
    name: str,
    semantic: str | None,
    state: State | None,
) -> tuple[Capability | None, ExportExclusionReason | None]:
    """Convert a binary sensor state."""
    if state is None or state.state == STATE_UNAVAILABLE:
        availability = Availability.UNAVAILABLE
        value = None
    elif state.state == STATE_UNKNOWN:
        availability = Availability.UNKNOWN
        value = None
    elif state.state in {STATE_ON, "cleaning"}:
        availability = Availability.AVAILABLE
        value = True
    elif state.state in {STATE_OFF, "docked", "idle", "paused", "returning"}:
        availability = Availability.AVAILABLE
        value = False
    else:
        return None, ExportExclusionReason.INVALID_BINARY_STATE

    return (
        Capability(
            source=source,
            kind=CapabilityKind.BINARY,
            name=name,
            value=value,
            availability=availability,
            semantic=semantic,
        ),
        None,
    )


def _numeric_capability(
    source: SourceIdentity,
    name: str,
    semantic: str | None,
    unit: str | None,
    state_class: str | None,
    state: State | None,
) -> tuple[Capability | None, ExportExclusionReason | None]:
    """Convert a numeric sensor state."""
    if semantic in _NON_NUMERIC_SENSOR_DEVICE_CLASSES:
        return None, ExportExclusionReason.NON_NUMERIC_DEVICE_CLASS

    if state is None or state.state in {STATE_UNKNOWN, STATE_UNAVAILABLE}:
        if not _has_numeric_metadata(semantic, unit, state_class):
            return None, ExportExclusionReason.MISSING_NUMERIC_METADATA
        availability = (
            Availability.UNKNOWN
            if state is not None and state.state == STATE_UNKNOWN
            else Availability.UNAVAILABLE
        )
        return (
            Capability(
                source=source,
                kind=CapabilityKind.NUMERIC,
                name=name,
                value=None,
                availability=availability,
                semantic=semantic,
                unit=unit,
                state_class=state_class,
            ),
            None,
        )

    try:
        value = float(state.state)
    except ValueError:
        return None, ExportExclusionReason.INVALID_NUMERIC_STATE
    if not isfinite(value):
        return None, ExportExclusionReason.INVALID_NUMERIC_STATE

    return (
        Capability(
            source=source,
            kind=CapabilityKind.NUMERIC,
            name=name,
            value=value,
            semantic=semantic,
            unit=unit,
            state_class=state_class,
        ),
        None,
    )


def _group_temperature_humidity_capabilities(
    hass: Any,
    entries: list[er.RegistryEntry],
    capabilities: list[Any],
    *,
    instance_id: str,
) -> list[Any]:
    """Group one labelled temperature and humidity pair per physical device."""
    from .core import CompoundCapability

    entries_by_id = {entry.id: entry for entry in entries}
    candidates: dict[str, dict[str, list[Capability]]] = {}
    for capability in capabilities:
        if not isinstance(capability, Capability):
            continue
        if capability.kind is not CapabilityKind.NUMERIC:
            continue
        if capability.semantic not in {"temperature", "humidity"}:
            continue
        entry = entries_by_id.get(capability.source.object_id)
        if entry is None or entry.device_id is None:
            continue
        by_semantic = candidates.setdefault(entry.device_id, {})
        by_semantic.setdefault(capability.semantic, []).append(capability)

    grouped_sources: set[SourceIdentity] = set()
    compounds: list[CompoundCapability] = []
    from homeassistant.helpers import device_registry as dr

    device_registry = dr.async_get(hass)
    for device_id, by_semantic in sorted(candidates.items()):
        temperatures = by_semantic.get("temperature", [])
        humidities = by_semantic.get("humidity", [])
        if len(temperatures) != 1 or len(humidities) != 1:
            continue
        temperature = temperatures[0]
        humidity = humidities[0]
        device = device_registry.async_get(device_id)
        name = (
            (device.name_by_user or device.name) if device is not None else None
        ) or f"{temperature.name} + {humidity.name}"
        availability = Availability.UNKNOWN
        if temperature.is_available or humidity.is_available:
            availability = Availability.AVAILABLE
        elif (
            temperature.availability is Availability.UNAVAILABLE
            or humidity.availability is Availability.UNAVAILABLE
        ):
            availability = Availability.UNAVAILABLE
        compounds.append(
            CompoundCapability(
                source=SourceIdentity(
                    system="home_assistant",
                    instance_id=instance_id,
                    object_id=device_id,
                    capability_id="temperature_humidity",
                ),
                name=name,
                capabilities=(temperature, humidity),
                availability=availability,
            )
        )
        grouped_sources.update({temperature.source, humidity.source})

    return [
        capability
        for capability in capabilities
        if capability.source not in grouped_sources
    ] + compounds


def _capability_from_entry(
    hass: Any,
    entry: er.RegistryEntry,
    state: State | None,
    *,
    instance_id: str,
) -> tuple[Capability | None, ExportExclusionReason | None]:
    """Convert one registry entry and current state."""
    from homeassistant.components.sensor import ATTR_STATE_CLASS
    from homeassistant.const import ATTR_DEVICE_CLASS, ATTR_UNIT_OF_MEASUREMENT

    attributes = state.attributes if state is not None else {}
    device_class = _first_string(
        attributes.get(ATTR_DEVICE_CLASS),
        entry.device_class,
        entry.original_device_class,
    )
    raw_unit = _first_string(
        attributes.get(ATTR_UNIT_OF_MEASUREMENT),
        entry.unit_of_measurement,
    )
    state_class = _first_string(
        attributes.get(ATTR_STATE_CLASS),
        (entry.capabilities or {}).get(ATTR_STATE_CLASS),
    )

    source = SourceIdentity(
        system="home_assistant",
        instance_id=instance_id,
        object_id=entry.id,
        capability_id="state",
    )
    name = (
        state.name
        if state is not None
        else er.async_get_full_entity_name(hass, entry) or entry.entity_id
    )

    if entry.domain in {"select", "input_select"}:
        return _selector_capability(source, name, state)

    if (
        entry.domain == _BINARY_SENSOR_DOMAIN
        or entry.domain in CONTROLLABLE_EXPORT_DOMAINS
    ):
        return _binary_capability(source, name, device_class, state)

    unit = _normalized_unit(raw_unit)
    return _numeric_capability(
        source,
        name,
        device_class,
        unit,
        state_class,
        state,
    )


def _has_numeric_metadata(
    semantic: str | None,
    unit: str | None,
    state_class: str | None,
) -> bool:
    """Return whether an unavailable sensor is known to be numeric."""
    return any(
        (
            semantic is not None,
            unit is not None,
            state_class is not None,
        )
    )


def _first_string(*values: Any) -> str | None:
    """Return the first non-empty string representation."""
    for value in values:
        if value is None:
            continue
        string_value = str(value).strip()
        if string_value:
            return string_value
    return None


def _normalized_unit(unit: str | None) -> str | None:
    """Translate common Home Assistant units to neutral unit keys."""
    if unit is None:
        return None
    return _UNIT_MAP.get(unit, unit)
