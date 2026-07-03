"""Sensor platform for Domoticz Import."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    LIGHT_LUX,
    PERCENTAGE,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfPrecipitationDepth,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
    UnitOfVolume,
    UnitOfVolumetricFlux,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import DomoticzRuntimeData
from .entity import DomoticzEntity
from .models import (
    DomoticzDevice,
    DomoticzMetric,
    extract_sensor_metrics,
)

_DEVICE_CLASS_MAP = {
    "battery": SensorDeviceClass.BATTERY,
    "energy": SensorDeviceClass.ENERGY,
    "humidity": SensorDeviceClass.HUMIDITY,
    "illuminance": SensorDeviceClass.ILLUMINANCE,
    "power": SensorDeviceClass.POWER,
    "atmospheric_pressure": SensorDeviceClass.ATMOSPHERIC_PRESSURE,
    "signal_strength": SensorDeviceClass.SIGNAL_STRENGTH,
    "temperature": SensorDeviceClass.TEMPERATURE,
    "voltage": SensorDeviceClass.VOLTAGE,
    "water": SensorDeviceClass.WATER,
    "precipitation": getattr(SensorDeviceClass, "PRECIPITATION", "precipitation"),
    "precipitation_intensity": getattr(
        SensorDeviceClass, "PRECIPITATION_INTENSITY", "precipitation_intensity"
    ),
    "wind_speed": getattr(SensorDeviceClass, "WIND_SPEED", "wind_speed"),
}

_STATE_CLASS_MAP = {
    "measurement": SensorStateClass.MEASUREMENT,
    "total_increasing": SensorStateClass.TOTAL_INCREASING,
}

_UNIT_MAP = {
    "celsius": UnitOfTemperature.CELSIUS,
    "percent": PERCENTAGE,
    "hpa": UnitOfPressure.HPA,
    "lux": LIGHT_LUX,
    "volt": UnitOfElectricPotential.VOLT,
    "watt": UnitOfPower.WATT,
    "kwh": UnitOfEnergy.KILO_WATT_HOUR,
    "m3": UnitOfVolume.CUBIC_METERS,
    "mm": UnitOfPrecipitationDepth.MILLIMETERS,
    "mm_per_hour": UnitOfVolumetricFlux.MILLIMETERS_PER_HOUR,
    "meter_per_second": UnitOfSpeed.METERS_PER_SECOND,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Domoticz sensors from a config entry."""
    runtime_data: DomoticzRuntimeData = entry.runtime_data
    coordinator = runtime_data.coordinator

    entities: list[DomoticzSensor] = []
    for device in coordinator.data.devices.values():
        entities.extend(
            DomoticzSensor(coordinator, entry, device, metric)
            for metric in extract_sensor_metrics(device)
        )

    async_add_entities(entities)


class DomoticzSensor(DomoticzEntity, SensorEntity):
    """Representation of one Domoticz sensor metric."""

    def __init__(
        self,
        coordinator,
        entry: ConfigEntry,
        device: DomoticzDevice,
        metric: DomoticzMetric,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, device)
        self._metric_key = metric.key
        self._attr_name = metric.name
        self._attr_unique_id = f"{entry.entry_id}_{device.idx}_{metric.key}"
        self._attr_device_class = _DEVICE_CLASS_MAP.get(metric.device_class)
        self._attr_state_class = _STATE_CLASS_MAP.get(metric.state_class)
        self._attr_native_unit_of_measurement = _UNIT_MAP.get(metric.unit)
        self._attr_entity_category = metric.entity_category
        self._attr_icon = metric.icon

    @property
    def available(self) -> bool:
        """Return if the sensor has a current matching metric."""
        return super().available and self._metric is not None

    @property
    def native_value(self) -> str | int | float | None:
        """Return the sensor value."""
        metric = self._metric
        return metric.native_value if metric is not None else None

    @property
    def _metric(self) -> DomoticzMetric | None:
        """Return the current metric from coordinator data."""
        device = self.domoticz_device
        if device is None:
            return None
        for metric in extract_sensor_metrics(device):
            if metric.key == self._metric_key:
                return metric
        return None
