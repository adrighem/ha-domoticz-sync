"""Tests for Domoticz value parsing."""

from custom_components.domoticz_import.models import (
    DomoticzDevice,
    extract_binary_state,
    extract_sensor_metrics,
)


def device(raw):
    """Build a Domoticz device for tests."""
    return DomoticzDevice.from_api(raw)


def metric_by_key(raw, key):
    """Return one extracted metric by key."""
    metrics = extract_sensor_metrics(device(raw))
    return next(metric for metric in metrics if metric.key == key)


def test_extracts_common_sensor_metrics():
    """Test extracting multiple typed metrics from one Domoticz response."""
    raw = {
        "idx": "12",
        "Name": "Living room climate",
        "Type": "Temp + Humidity + Baro",
        "Temp": 21.4,
        "Humidity": "52",
        "Barometer": "1012",
        "BatteryLevel": 87,
    }

    metrics = {metric.key: metric for metric in extract_sensor_metrics(device(raw))}

    assert metrics["temperature"].native_value == 21.4
    assert metrics["temperature"].unit == "celsius"
    assert metrics["humidity"].native_value == 52.0
    assert metrics["humidity"].unit == "percent"
    assert metrics["barometer"].native_value == 1012.0
    assert metrics["barometer"].device_class == "atmospheric_pressure"
    assert metrics["battery_level"].entity_category == "diagnostic"


def test_extracts_counter_unit_from_value_text():
    """Test counter parsing keeps the value and discovers the unit."""
    metric = metric_by_key(
        {
            "idx": "42",
            "Name": "Electricity",
            "Type": "General",
            "SubType": "kWh",
            "CounterToday": "4.212 kWh",
        },
        "counter_today",
    )

    assert metric.native_value == 4.212
    assert metric.unit == "kwh"
    assert metric.state_class == "total_increasing"


def test_extracts_text_fallback():
    """Test text devices are imported as string sensors."""
    metric = metric_by_key(
        {
            "idx": "77",
            "Name": "Waste pickup",
            "Type": "General",
            "SubType": "Text",
            "Data": "Tomorrow: paper",
        },
        "text",
    )

    assert metric.native_value == "Tomorrow: paper"


def test_extracts_generic_numeric_fallback():
    """Test generic Data values are imported when no typed field exists."""
    metric = metric_by_key(
        {
            "idx": "78",
            "Name": "Current load",
            "Type": "General",
            "SubType": "Custom Sensor",
            "Data": "532 Watt",
        },
        "value",
    )

    assert metric.native_value == 532.0
    assert metric.unit == "watt"
    assert metric.device_class == "power"


def test_extracts_motion_binary_sensor():
    """Test Domoticz motion devices become motion binary sensors."""
    state = extract_binary_state(
        device(
            {
                "idx": "3",
                "Name": "Hall motion",
                "Type": "Light/Switch",
                "SwitchType": "Motion Sensor",
                "Status": "On",
            }
        )
    )

    assert state is not None
    assert state.is_on is True
    assert state.device_class == "motion"
    assert state.name == "Motion"


def test_ignores_non_binary_sensor_values():
    """Test numeric sensor values are not duplicated as binary sensors."""
    state = extract_binary_state(
        device(
            {
                "idx": "4",
                "Name": "Outdoor temp",
                "Type": "Temp",
                "Data": "8.2 C",
            }
        )
    )

    assert state is None
