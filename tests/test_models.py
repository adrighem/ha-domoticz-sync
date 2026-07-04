"""Tests for Domoticz value parsing."""

from custom_components.domoticz_sync.models import (
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


def test_extracts_rain_meter_metrics():
    """Test extracting multiple metrics from a Domoticz rain meter device."""
    raw = {
        "idx": "14",
        "Name": "Backyard Rain",
        "Type": "Rain",
        "Rain": 15.4,
        "RainRate": 1.2,
        "BatteryLevel": 90,
    }

    metrics = {metric.key: metric for metric in extract_sensor_metrics(device(raw))}

    assert metrics["rain"].native_value == 15.4
    assert metrics["rain"].unit == "mm"
    assert metrics["rain"].device_class == "precipitation"
    assert metrics["rain"].state_class == "total_increasing"

    assert metrics["rain_rate"].native_value == 1.2
    assert metrics["rain_rate"].unit == "mm_per_hour"
    assert metrics["rain_rate"].device_class == "precipitation_intensity"
    assert metrics["rain_rate"].state_class == "measurement"


def test_extracts_p1_smart_meter_metrics():
    """Test extracting all 6 metrics from a P1 Smart Meter device."""
    raw = {
        "idx": "15",
        "Name": "Electricity Meter",
        "Type": "P1 Smart Meter",
        "SubType": "Energy",
        "Data": "1245589;658097;695572;1836977;103;102",
        "BatteryLevel": 255,
    }

    metrics = {metric.key: metric for metric in extract_sensor_metrics(device(raw))}

    assert metrics["energy_import_t1"].native_value == 1245.589
    assert metrics["energy_import_t1"].unit == "kwh"
    assert metrics["energy_import_t1"].device_class == "energy"
    assert metrics["energy_import_t1"].state_class == "total_increasing"

    assert metrics["energy_import_t2"].native_value == 658.097
    assert metrics["energy_import_t2"].unit == "kwh"

    assert metrics["energy_export_t1"].native_value == 695.572
    assert metrics["energy_export_t1"].unit == "kwh"

    assert metrics["energy_export_t2"].native_value == 1836.977
    assert metrics["energy_export_t2"].unit == "kwh"

    assert metrics["power_import"].native_value == 103.0
    assert metrics["power_import"].unit == "watt"
    assert metrics["power_import"].device_class == "power"
    assert metrics["power_import"].state_class == "measurement"

    assert metrics["power_export"].native_value == 102.0
    assert metrics["power_export"].unit == "watt"
    assert metrics["power_export"].device_class == "power"
    assert metrics["power_export"].state_class == "measurement"


def test_extracts_bar_pressure_metrics():
    """Test extracting bar pressure metrics."""
    raw = {
        "idx": "16",
        "Name": "CV Pressure",
        "Type": "General",
        "SubType": "Pressure",
        "Data": "1.8 Bar",
    }

    metrics = {metric.key: metric for metric in extract_sensor_metrics(device(raw))}

    assert metrics["value"].native_value == 1.8
    assert metrics["value"].unit == "bar"
    assert metrics["value"].device_class == "atmospheric_pressure"
    assert metrics["value"].state_class == "measurement"


def test_extracts_new_units():
    """Test extracting newer units like Fahrenheit, Amperes, Hertz, and Liters."""
    fahrenheit_dev = {
        "idx": "17",
        "Name": "Outdoor F",
        "Type": "Temp",
        "Data": "68.0 F",
    }
    amp_dev = {
        "idx": "18",
        "Name": "Smart Plug Current",
        "Type": "General",
        "SubType": "Custom Sensor",
        "Data": "1.2 A",
    }
    hertz_dev = {
        "idx": "19",
        "Name": "Grid Frequency",
        "Type": "General",
        "SubType": "Custom Sensor",
        "Data": "50.0 Hz",
    }
    liters_dev = {
        "idx": "20",
        "Name": "Water Meter Liters",
        "Type": "General",
        "SubType": "Custom Sensor",
        "Data": "150.0 Liters",
    }

    m_f = extract_sensor_metrics(device(fahrenheit_dev))[0]
    assert m_f.native_value == 68.0
    assert m_f.unit == "fahrenheit"
    assert m_f.device_class == "temperature"

    m_a = extract_sensor_metrics(device(amp_dev))[0]
    assert m_a.native_value == 1.2
    assert m_a.unit == "A"
    assert m_a.device_class == "current"

    m_hz = extract_sensor_metrics(device(hertz_dev))[0]
    assert m_hz.native_value == 50.0
    assert m_hz.unit == "hz"
    assert m_hz.device_class == "frequency"

    m_l = extract_sensor_metrics(device(liters_dev))[0]
    assert m_l.native_value == 150.0
    assert m_l.unit == "l"
    assert m_l.device_class == "water"


def test_no_redundant_value_metric():
    """Test that a redundant 'value' metric is not created when a primary metric exists."""
    raw = {
        "idx": "30",
        "Name": "Outside Temperature",
        "Type": "Temp",
        "Temp": 18.5,
        "Data": "18.5 C",
        "BatteryLevel": 90,
    }

    metrics = {metric.key: metric for metric in extract_sensor_metrics(device(raw))}

    # Primary 'temperature' and diagnostic 'battery_level' should exist
    assert "temperature" in metrics
    assert "battery_level" in metrics
    assert metrics["temperature"].native_value == 18.5

    # But the generic 'value' metric should NOT exist
    assert "value" not in metrics
