"""Unified in-memory DomoticzEx mocks for tests."""

from __future__ import annotations

from types import ModuleType
from typing import Any

MISSING: Any = object()
WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class FakeConnection:
    """Callback-native Domoticz connection stand-in."""

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.sent: list[Any] = []
        self.connecting = False
        self.connected = False
        self.disconnected = False

    def Connect(self) -> None:
        self.connecting = True

    def Connected(self) -> bool:
        return self.connected

    def Connecting(self) -> bool:
        return self.connecting

    def Send(self, document: Any) -> None:
        self.sent.append(document)

    def Disconnect(self) -> None:
        self.connected = False
        self.connecting = False
        self.disconnected = True


class FakeUnit:
    """In-memory DomoticzEx unit with observable persistence calls."""

    def __init__(self, domoticz: FakeDomoticz, **kwargs: Any) -> None:
        self._domoticz = domoticz
        self._device_id = kwargs.get("DeviceID")
        self.Name = kwargs.get("Name")
        self.Unit = kwargs.get("Unit", 1)
        self.Type = kwargs.get("Type", 0)
        self.SubType = kwargs.get("Subtype", kwargs.get("SubType", 0))
        self.SwitchType = kwargs.get("Switchtype", kwargs.get("SwitchType", 0))
        self.Options = dict(kwargs.get("Options", {}))
        self.Used = kwargs.get("Used", 0)
        self.nValue = kwargs.get("nValue", 0)
        self.sValue = kwargs.get("sValue", "")
        self.updates: list[dict[str, Any]] = []
        self.refreshes = 0
        self.deleted = False

    def Update(self, **kwargs: Any) -> None:
        self.updates.append(dict(kwargs))

    def Refresh(self) -> None:
        self.refreshes += 1
        if getattr(self._domoticz, "corrupt_refreshes", False):
            self.sValue = "not-persisted"

    def Delete(self) -> None:
        self.deleted = True
        device = self._domoticz.devices.get(self._device_id)
        if device is not None:
            device.Units.pop(self.Unit, None)

    def __repr__(self) -> str:
        return (
            f"FakeUnit(Unit={self.Unit}, Type={self.Type}, "
            f"SubType={self.SubType}, SwitchType={self.SwitchType}, "
            f"nValue={self.nValue}, sValue={self.sValue!r})"
        )


class FakeDevice:
    """Container matching DomoticzEx extended device model."""

    def __init__(
        self,
        domoticz_or_target_id: Any,
        device_id: str | None = None,
    ) -> None:
        if isinstance(domoticz_or_target_id, str) and device_id is None:
            self._domoticz = None
            self.DeviceID = domoticz_or_target_id
        else:
            self._domoticz = domoticz_or_target_id
            self.DeviceID = device_id
        self._timed_out = 0
        self.Units: dict[int, FakeUnit] = {}

    @property
    def TimedOut(self) -> int:
        return self._timed_out

    @TimedOut.setter
    def TimedOut(self, value: int) -> None:
        self._timed_out = value

    def __repr__(self) -> str:
        units_list = list(self.Units.keys())
        return f"FakeDevice(DeviceID={self.DeviceID!r}, Units={units_list})"


class FakeUnitCreator:
    """Deferred DomoticzEx Unit creator."""

    def __init__(self, domoticz: FakeDomoticz, kwargs: dict[str, Any]) -> None:
        self._domoticz = domoticz
        self._kwargs = kwargs

    def Create(self) -> FakeUnit:
        self._domoticz.create_calls.append(dict(self._kwargs))
        unit = FakeUnit(self._domoticz, **self._kwargs)
        if getattr(self._domoticz, "persist_creates", True):
            target_id = unit._device_id or self._kwargs.get("DeviceID")
            assert isinstance(target_id, str)
            device = self._domoticz.devices.setdefault(
                target_id,
                FakeDevice(self._domoticz, target_id),
            )
            device.Units[unit.Unit] = unit
        return unit


class FakeDomoticz(ModuleType):
    """DomoticzEx module with in-memory configuration and connections."""

    def __init__(self) -> None:
        super().__init__("DomoticzEx")
        self.configuration: dict[str, Any] = {}
        self.configuration_writes: list[dict[str, Any]] = []
        self.connections: list[FakeConnection] = []
        self.devices: dict[str, FakeDevice] = {}
        self.create_calls: list[dict[str, Any]] = []
        self.persist_creates = True
        self.corrupt_refreshes = False
        self.logs: list[str] = []
        self.statuses: list[str] = []
        self.errors: list[str] = []
        self.heartbeat_seconds: int | None = None

    def Configuration(self, config: Any = MISSING) -> dict[str, Any]:
        if config is not MISSING:
            self.configuration = dict(config)
            self.configuration_writes.append(dict(config))
        return dict(self.configuration)

    def Connection(self, **kwargs: Any) -> FakeConnection:
        connection = FakeConnection(**kwargs)
        self.connections.append(connection)
        return connection

    def Heartbeat(self, seconds: int) -> None:
        self.heartbeat_seconds = seconds

    def Unit(self, **kwargs: Any) -> FakeUnitCreator:
        return FakeUnitCreator(self, kwargs)

    def Log(self, message: str) -> None:
        self.logs.append(message)

    def Status(self, message: str) -> None:
        self.statuses.append(message)

    def Error(self, message: str) -> None:
        self.errors.append(message)
