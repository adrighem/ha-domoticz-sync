"""Domoticz device models and value extraction helpers."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

STATE_CLASS_MEASUREMENT = "measurement"
STATE_CLASS_TOTAL_INCREASING = "total_increasing"

ENTITY_CATEGORY_DIAGNOSTIC = "diagnostic"

DEVICE_CLASS_BATTERY = "battery"
DEVICE_CLASS_HUMIDITY = "humidity"
DEVICE_CLASS_ILLUMINANCE = "illuminance"
DEVICE_CLASS_POWER = "power"
DEVICE_CLASS_PRESSURE = "atmospheric_pressure"
DEVICE_CLASS_TEMPERATURE = "temperature"
DEVICE_CLASS_VOLTAGE = "voltage"
DEVICE_CLASS_ENERGY = "energy"
DEVICE_CLASS_WATER = "water"
DEVICE_CLASS_PRECIPITATION = "precipitation"
DEVICE_CLASS_PRECIPITATION_INTENSITY = "precipitation_intensity"
DEVICE_CLASS_WIND_SPEED = "wind_speed"
DEVICE_CLASS_CURRENT = "current"
DEVICE_CLASS_FREQUENCY = "frequency"

UNIT_CELSIUS = "celsius"
UNIT_FAHRENHEIT = "fahrenheit"
UNIT_PERCENT = "percent"
UNIT_HPA = "hpa"
UNIT_LUX = "lux"
UNIT_VOLT = "volt"
UNIT_WATT = "watt"
UNIT_KWH = "kwh"
UNIT_M3 = "m3"
UNIT_LITERS = "l"
UNIT_MM = "mm"
UNIT_MM_PER_HOUR = "mm_per_hour"
UNIT_METER_PER_SECOND = "meter_per_second"
UNIT_BAR = "bar"
UNIT_AMPERE = "A"
UNIT_HERTZ = "hz"

_NUMBER_RE = re.compile(r"[-+]?\d+(?:[.,]\d+)?")


@dataclass(frozen=True, slots=True)
class DomoticzDevice:
    """A single device returned by Domoticz."""

    idx: str
    name: str
    type: str | None
    sub_type: str | None
    switch_type: str | None
    data: str | None
    status: str | None
    last_update: str | None
    hardware_name: str | None
    hardware_id: int | None
    device_id: str | None
    raw: Mapping[str, Any]

    @classmethod
    def from_api(cls, raw: Mapping[str, Any]) -> DomoticzDevice:
        """Create a Domoticz device from an API dictionary."""
        idx = _as_str(raw.get("idx") or raw.get("Idx") or raw.get("ID"))
        name = _as_str(raw.get("Name") or raw.get("name") or idx)

        raw_hw_id = raw.get("HardwareID")
        try:
            hardware_id = int(raw_hw_id) if raw_hw_id is not None else None
        except (ValueError, TypeError):
            hardware_id = None

        device_id = _optional_str(raw.get("ID"))

        return cls(
            idx=idx,
            name=name,
            type=_optional_str(raw.get("Type")),
            sub_type=_optional_str(raw.get("SubType")),
            switch_type=_optional_str(raw.get("SwitchType")),
            data=_optional_str(raw.get("Data")),
            status=_optional_str(raw.get("Status")),
            last_update=_optional_str(raw.get("LastUpdate")),
            hardware_name=_optional_str(raw.get("HardwareName")),
            hardware_id=hardware_id,
            device_id=device_id,
            raw=raw,
        )


@dataclass(frozen=True, slots=True)
class DomoticzMetric:
    """A Home Assistant sensor value extracted from a Domoticz device."""

    key: str
    name: str
    native_value: str | int | float
    device_class: str | None = None
    state_class: str | None = None
    unit: str | None = None
    entity_category: str | None = None
    icon: str | None = None


@dataclass(frozen=True, slots=True)
class BinaryState:
    """A Home Assistant binary sensor value extracted from a Domoticz device."""

    is_on: bool
    device_class: str | None = None
    name: str = "State"


@dataclass(frozen=True, slots=True)
class _MetricSpec:
    key: str
    name: str
    fields: tuple[str, ...]
    device_class: str | None = None
    unit: str | None = None
    state_class: str | None = STATE_CLASS_MEASUREMENT
    entity_category: str | None = None
    icon: str | None = None


_METRIC_SPECS: tuple[_MetricSpec, ...] = (
    _MetricSpec(
        "temperature",
        "Temperature",
        ("Temp", "Temperature"),
        DEVICE_CLASS_TEMPERATURE,
        UNIT_CELSIUS,
    ),
    _MetricSpec(
        "humidity",
        "Humidity",
        ("Humidity",),
        DEVICE_CLASS_HUMIDITY,
        UNIT_PERCENT,
    ),
    _MetricSpec(
        "barometer",
        "Pressure",
        ("Barometer", "Pressure"),
        DEVICE_CLASS_PRESSURE,
        UNIT_HPA,
    ),
    _MetricSpec(
        "setpoint",
        "Setpoint",
        ("SetPoint",),
        DEVICE_CLASS_TEMPERATURE,
        UNIT_CELSIUS,
    ),
    _MetricSpec("lux", "Illuminance", ("Lux",), DEVICE_CLASS_ILLUMINANCE, UNIT_LUX),
    _MetricSpec("uv_index", "UV index", ("UVI",), icon="mdi:white-balance-sunny"),
    _MetricSpec(
        "voltage",
        "Voltage",
        ("Voltage",),
        DEVICE_CLASS_VOLTAGE,
        UNIT_VOLT,
    ),
    _MetricSpec(
        "power", "Power", ("Usage", "UsageDeliv"), DEVICE_CLASS_POWER, UNIT_WATT
    ),
    _MetricSpec(
        "counter_today",
        "Today",
        ("CounterToday",),
        state_class=STATE_CLASS_TOTAL_INCREASING,
    ),
    _MetricSpec(
        "counter",
        "Counter",
        ("Counter",),
        state_class=STATE_CLASS_TOTAL_INCREASING,
    ),
    _MetricSpec(
        "rain",
        "Rain",
        ("Rain",),
        DEVICE_CLASS_PRECIPITATION,
        UNIT_MM,
        STATE_CLASS_TOTAL_INCREASING,
    ),
    _MetricSpec(
        "rain_rate",
        "Rain rate",
        ("RainRate",),
        DEVICE_CLASS_PRECIPITATION_INTENSITY,
        UNIT_MM_PER_HOUR,
    ),
    _MetricSpec(
        "wind_speed",
        "Wind speed",
        ("Speed", "WindSpeed"),
        DEVICE_CLASS_WIND_SPEED,
        UNIT_METER_PER_SECOND,
    ),
    _MetricSpec(
        "battery_level",
        "Battery",
        ("BatteryLevel",),
        DEVICE_CLASS_BATTERY,
        UNIT_PERCENT,
        entity_category=ENTITY_CATEGORY_DIAGNOSTIC,
    ),
    _MetricSpec(
        "signal_level",
        "Signal",
        ("SignalLevel",),
        icon="mdi:wifi",
        entity_category=ENTITY_CATEGORY_DIAGNOSTIC,
    ),
)

_TRUE_STATES = {
    "on",
    "open",
    "motion",
    "detected",
    "alarm",
    "alert",
    "active",
    "panic",
    "triggered",
}
_FALSE_STATES = {
    "off",
    "closed",
    "normal",
    "no motion",
    "not detected",
    "clear",
    "inactive",
    "safe",
}


def extract_sensor_metrics(device: DomoticzDevice) -> list[DomoticzMetric]:
    """Extract Home Assistant sensor metrics from a Domoticz device."""
    # Special handling for P1 Smart Meter (multi-sensor energy/power)
    if device.type == "P1 Smart Meter" or (
        device.sub_type and "p1" in device.sub_type.lower()
    ):
        data_str = (device.data or "").strip()
        parts = data_str.split(";")
        if len(parts) == 6:
            try:
                import_t1 = float(parts[0]) / 1000.0  # Wh to kWh
                import_t2 = float(parts[1]) / 1000.0  # Wh to kWh
                export_t1 = float(parts[2]) / 1000.0  # Wh to kWh
                export_t2 = float(parts[3]) / 1000.0  # Wh to kWh
                power_import = float(parts[4])        # Watt
                power_export = float(parts[5])        # Watt

                # Include standard diagnostic sensors (battery and signal) if they exist
                diagnostics: list[DomoticzMetric] = []
                for spec in _METRIC_SPECS:
                    if spec.entity_category == ENTITY_CATEGORY_DIAGNOSTIC:
                        for field in spec.fields:
                            if field in device.raw:
                                parsed_val = _parse_float(device.raw[field])
                                if parsed_val is not None:
                                    diagnostics.append(
                                        DomoticzMetric(
                                            key=spec.key,
                                            name=spec.name,
                                            native_value=parsed_val,
                                            device_class=spec.device_class,
                                            state_class=spec.state_class,
                                            unit=spec.unit,
                                            entity_category=spec.entity_category,
                                            icon=spec.icon,
                                        )
                                    )
                                break

                return [
                    DomoticzMetric(
                        "energy_import_t1",
                        "Energy Import T1",
                        import_t1,
                        DEVICE_CLASS_ENERGY,
                        STATE_CLASS_TOTAL_INCREASING,
                        UNIT_KWH,
                    ),
                    DomoticzMetric(
                        "energy_import_t2",
                        "Energy Import T2",
                        import_t2,
                        DEVICE_CLASS_ENERGY,
                        STATE_CLASS_TOTAL_INCREASING,
                        UNIT_KWH,
                    ),
                    DomoticzMetric(
                        "energy_export_t1",
                        "Energy Export T1",
                        export_t1,
                        DEVICE_CLASS_ENERGY,
                        STATE_CLASS_TOTAL_INCREASING,
                        UNIT_KWH,
                    ),
                    DomoticzMetric(
                        "energy_export_t2",
                        "Energy Export T2",
                        export_t2,
                        DEVICE_CLASS_ENERGY,
                        STATE_CLASS_TOTAL_INCREASING,
                        UNIT_KWH,
                    ),
                    DomoticzMetric(
                        "power_import",
                        "Power Import",
                        power_import,
                        DEVICE_CLASS_POWER,
                        STATE_CLASS_MEASUREMENT,
                        UNIT_WATT,
                    ),
                    DomoticzMetric(
                        "power_export",
                        "Power Export",
                        power_export,
                        DEVICE_CLASS_POWER,
                        STATE_CLASS_MEASUREMENT,
                        UNIT_WATT,
                    ),
                ] + diagnostics
            except ValueError:
                pass

    metrics: list[DomoticzMetric] = []
    seen_keys: set[str] = set()

    for spec in _METRIC_SPECS:
        for field in spec.fields:
            if field not in device.raw:
                continue
            raw_value = device.raw[field]
            parsed = _parse_float(raw_value)
            if parsed is None:
                continue

            unit = spec.unit
            if spec.key in {"counter_today", "counter"}:
                unit = _unit_from_text(_as_str(raw_value)) or _counter_unit(device)

            metrics.append(
                DomoticzMetric(
                    key=spec.key,
                    name=spec.name,
                    native_value=parsed,
                    device_class=spec.device_class or _device_class_for_unit(unit),
                    state_class=spec.state_class,
                    unit=unit,
                    entity_category=spec.entity_category,
                    icon=spec.icon,
                )
            )
            seen_keys.add(spec.key)
            break

    has_primary_metric = any(
        m.entity_category != ENTITY_CATEGORY_DIAGNOSTIC for m in metrics
    )
    if not has_primary_metric:
        fallback = _fallback_metric(device)
        if fallback is not None and fallback.key not in seen_keys:
            metrics.append(fallback)

    return metrics


def extract_binary_state(device: DomoticzDevice) -> BinaryState | None:
    """Extract a Home Assistant binary sensor state from a Domoticz device."""
    status = (device.status or device.data or "").strip().lower()
    if not status:
        return None

    state: bool | None = None
    if status in _TRUE_STATES:
        state = True
    elif status in _FALSE_STATES:
        state = False
    elif status.startswith("on"):
        state = True
    elif status.startswith("off"):
        state = False

    if state is None:
        return None

    combined = " ".join(
        part.lower()
        for part in (device.type, device.sub_type, device.switch_type, device.name)
        if part
    )

    if any(word in combined for word in ("motion", "pir")):
        return BinaryState(state, "motion", "Motion")
    if any(word in combined for word in ("door", "contact")):
        return BinaryState(state, "door", "Door")
    if "smoke" in combined:
        return BinaryState(state, "smoke", "Smoke")
    if any(word in combined for word in ("water", "leak", "flood")):
        return BinaryState(state, "moisture", "Moisture")
    if "lock" in combined:
        return BinaryState(state, "lock", "Lock")
    if any(word in combined for word in ("presence", "occupancy")):
        return BinaryState(state, "occupancy", "Occupancy")
    if any(word in combined for word in ("security", "tamper", "alarm")):
        return BinaryState(state, "safety", "Safety")
    if any(word in combined for word in ("switch", "light")):
        return BinaryState(state)

    return None


def _fallback_metric(device: DomoticzDevice) -> DomoticzMetric | None:
    """Build a generic metric from Data when Domoticz gives no typed fields."""
    data = (device.data or "").strip()
    if not data:
        return None

    combined = " ".join(
        part.lower() for part in (device.type, device.sub_type, device.name) if part
    )

    if "text" in combined:
        return DomoticzMetric("text", "Text", data, icon="mdi:text")

    value = _parse_float(data)
    if value is None:
        return None

    unit = _unit_from_text(data)
    return DomoticzMetric(
        key="value",
        name="Value",
        native_value=value,
        device_class=_device_class_for_unit(unit),
        state_class=STATE_CLASS_MEASUREMENT,
        unit=unit,
    )


def _counter_unit(device: DomoticzDevice) -> str | None:
    """Guess a counter unit from Domoticz metadata."""
    text = " ".join(
        part.lower() for part in (device.type, device.sub_type, device.data) if part
    )
    if "kwh" in text or "energy" in text or "electric" in text:
        return UNIT_KWH
    if "water" in text or "gas" in text:
        return UNIT_M3
    return _unit_from_text(text)


def _unit_from_text(value: str) -> str | None:
    """Map a Domoticz value string to a known Home Assistant unit key."""
    lowered = value.lower()
    if "kwh" in lowered:
        return UNIT_KWH
    if "watt" in lowered or re.search(r"\bw\b", lowered):
        return UNIT_WATT
    if "lux" in lowered:
        return UNIT_LUX
    if "hpa" in lowered or "mbar" in lowered:
        return UNIT_HPA
    if "%" in lowered:
        return UNIT_PERCENT
    if "bar" in lowered:
        return UNIT_BAR
    if "volt" in lowered or re.search(r"\bv\b", lowered):
        return UNIT_VOLT
    if "amp" in lowered or lowered.endswith(" a") or " a " in lowered:
        return UNIT_AMPERE
    if "hz" in lowered or "hertz" in lowered:
        return UNIT_HERTZ
    if "liter" in lowered or "litre" in lowered or re.search(r"\bl\b", lowered):
        return UNIT_LITERS
    if "mm/h" in lowered:
        return UNIT_MM_PER_HOUR
    if "mm" in lowered:
        return UNIT_MM
    if "m3" in lowered or "m^3" in lowered:
        return UNIT_M3
    if "c" in lowered and any(token in lowered for token in ("deg", "celsius", " c")):
        return UNIT_CELSIUS
    if "f" in lowered and any(
        token in lowered for token in ("deg", "fahrenheit", " f")
    ):
        return UNIT_FAHRENHEIT
    return None


def _device_class_for_unit(unit: str | None) -> str | None:
    """Return a Home Assistant sensor device class key for a unit key."""
    return {
        UNIT_CELSIUS: DEVICE_CLASS_TEMPERATURE,
        UNIT_FAHRENHEIT: DEVICE_CLASS_TEMPERATURE,
        UNIT_HPA: DEVICE_CLASS_PRESSURE,
        UNIT_BAR: DEVICE_CLASS_PRESSURE,
        UNIT_LUX: DEVICE_CLASS_ILLUMINANCE,
        UNIT_VOLT: DEVICE_CLASS_VOLTAGE,
        UNIT_AMPERE: DEVICE_CLASS_CURRENT,
        UNIT_WATT: DEVICE_CLASS_POWER,
        UNIT_KWH: DEVICE_CLASS_ENERGY,
        UNIT_M3: DEVICE_CLASS_WATER,
        UNIT_LITERS: DEVICE_CLASS_WATER,
        UNIT_MM: DEVICE_CLASS_PRECIPITATION,
        UNIT_MM_PER_HOUR: DEVICE_CLASS_PRECIPITATION_INTENSITY,
        UNIT_METER_PER_SECOND: DEVICE_CLASS_WIND_SPEED,
        UNIT_HERTZ: DEVICE_CLASS_FREQUENCY,
    }.get(unit)


def _parse_float(value: Any) -> float | None:
    """Parse the first number from a Domoticz value."""
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)

    match = _NUMBER_RE.search(_as_str(value))
    if match is None:
        return None
    try:
        return float(match.group(0).replace(",", "."))
    except ValueError:
        return None


def _optional_str(value: Any) -> str | None:
    """Return a non-empty string or None."""
    if value is None:
        return None
    string_value = _as_str(value).strip()
    return string_value or None


def _as_str(value: Any) -> str:
    """Return a string representation of an API value."""
    return "" if value is None else str(value)
