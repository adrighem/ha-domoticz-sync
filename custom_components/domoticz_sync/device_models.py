"""Core Domoticz device and metric dataclasses with value helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


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
        except ValueError, TypeError:
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


def _optional_str(value: Any) -> str | None:
    """Return a non-empty string or None."""
    if value is None:
        return None
    string_value = _as_str(value).strip()
    return string_value or None


def _as_str(value: Any) -> str:
    """Return a string representation of an API value."""
    return "" if value is None else str(value)
