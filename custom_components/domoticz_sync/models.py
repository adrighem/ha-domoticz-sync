"""Domoticz device models and value extraction helpers."""

from __future__ import annotations

from dataclasses import dataclass

from .device_models import DomoticzDevice, DomoticzMetric
from .metric_extractors import extract_sensor_metrics


@dataclass(frozen=True, slots=True)
class BinaryState:
    """A Home Assistant binary sensor value extracted from a Domoticz device."""

    is_on: bool
    device_class: str | None = None
    name: str = "State"


@dataclass(frozen=True, slots=True)
class SwitchState:
    """A Home Assistant switch state extracted from a Domoticz device."""

    is_on: bool
    name: str = "Switch"
    device_class: str | None = None


@dataclass(frozen=True, slots=True)
class ButtonState:
    """A Home Assistant button representation for a Domoticz trigger device."""

    name: str = "Button"
    command: str = "On"


_PASSIVE_SENSOR_SWITCH_TYPES = frozenset(
    {
        "motion sensor",
        "contact",
        "dusk sensor",
        "smoke detector",
        "door contact",
        "door lock",
    }
)
_COVER_SWITCH_TYPES = frozenset(
    {
        "blinds",
        "blinds inverted",
        "blinds percentage",
        "blinds percentage inverted",
        "venetian blinds eu",
        "venetian blinds us",
        "roller shutter",
    }
)
_CONTROLLABLE_SWITCH_TYPES = frozenset(
    {
        "on/off",
        "x10 siren",
    }
)
_MOMENTARY_BUTTON_TYPES = frozenset(
    {
        "push on button",
        "push off button",
        "doorbell",
    }
)
_TRUE_STATES = frozenset(
    {
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
)
_FALSE_STATES = frozenset(
    {
        "off",
        "closed",
        "normal",
        "no motion",
        "not detected",
        "clear",
        "inactive",
        "safe",
    }
)


def extract_button_state(device: DomoticzDevice) -> ButtonState | None:
    """Extract a Home Assistant button representation from a Domoticz device."""
    switch_type = (device.switch_type or "").strip().lower()
    if switch_type not in _MOMENTARY_BUTTON_TYPES:
        return None

    command = "Off" if switch_type == "push off button" else "On"
    return ButtonState(name="Press", command=command)


def extract_switch_state(device: DomoticzDevice) -> SwitchState | None:
    """Extract a Home Assistant switch state from a Domoticz device."""
    switch_type = (device.switch_type or "").strip().lower()
    dev_type = (device.type or "").strip().lower()

    if (
        switch_type in _PASSIVE_SENSOR_SWITCH_TYPES
        or switch_type in _COVER_SWITCH_TYPES
        or switch_type in _MOMENTARY_BUTTON_TYPES
    ):
        return None

    combined = " ".join(
        part.lower()
        for part in (device.type, device.sub_type, device.switch_type, device.name)
        if part
    )

    if (
        any(
            word in combined
            for word in (
                "motion",
                "pir",
                "smoke",
                "leak",
                "flood",
                "presence",
                "occupancy",
                "tamper",
            )
        )
        and switch_type not in _CONTROLLABLE_SWITCH_TYPES
    ):
        return None

    is_switch = (
        switch_type in _CONTROLLABLE_SWITCH_TYPES
        or ("light/switch" in dev_type and not switch_type)
        or ("lighting" in dev_type and not switch_type)
        or ("switch" in dev_type and not switch_type)
    )
    if not is_switch:
        return None

    status = (device.status or device.data or "").strip().lower()
    if not status:
        return None

    state: bool | None = None
    if (
        status in _TRUE_STATES
        or status.startswith("on")
        or status.startswith("set level")
    ):
        state = True
    elif status in _FALSE_STATES or status.startswith("off"):
        state = False

    if state is None:
        return None

    device_class = (
        "outlet"
        if any(w in combined for w in ("plug", "socket", "outlet"))
        else "switch"
    )
    return SwitchState(is_on=state, name="Switch", device_class=device_class)


def extract_binary_state(device: DomoticzDevice) -> BinaryState | None:
    """Extract a Home Assistant binary sensor state from a Domoticz device."""
    if (
        extract_switch_state(device) is not None
        or extract_button_state(device) is not None
    ):
        return None

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


__all__ = [
    "DomoticzDevice",
    "DomoticzMetric",
    "BinaryState",
    "SwitchState",
    "ButtonState",
    "extract_sensor_metrics",
    "extract_button_state",
    "extract_switch_state",
    "extract_binary_state",
]
