"""Tests for the Domoticz API client."""

import asyncio
from base64 import b64encode
from hmac import compare_digest
from unittest.mock import MagicMock

import pytest
from aiohttp import ClientResponseError

import custom_components.domoticz_sync.api as api_module
from custom_components.domoticz_sync.api import (
    DomoticzApi,
    DomoticzApiError,
    DomoticzAuthError,
    DomoticzConnectionError,
    DomoticzDeviceUnavailableError,
    DomoticzTimeoutError,
    normalize_base_url,
)


def test_legacy_basic_auth_encoder_fallback(monkeypatch):
    """Use aiohttp's legacy encoder when the modern helper is unavailable."""
    state = {"constructed": False, "encoded": False}

    class LegacyBasicAuth:
        """Test double for aiohttp.BasicAuth."""

        def __init__(self, username, password, encoding):
            if (
                username != "placeholder-user"
                or password != "placeholder-password"
                or encoding != "latin1"
            ):
                raise AssertionError("Legacy Basic Auth arguments did not match")
            state["constructed"] = True

        def encode(self):
            state["encoded"] = True
            return "fallback-result"

    monkeypatch.setattr(api_module, "_aiohttp_encode_basic_auth", None)
    monkeypatch.setattr(api_module, "_legacy_basic_auth", LegacyBasicAuth)

    result = api_module._encode_basic_auth_header(
        "placeholder-user",
        "placeholder-password",
    )

    assert result == "fallback-result"
    assert state == {"constructed": True, "encoded": True}


class MockResponse:
    """Async context manager response for aiohttp-style calls."""

    def __init__(self, status=200, json_data=None, raise_error=None):
        """Initialize the response."""
        self.status = status
        self._json_data = json_data if json_data is not None else {}
        self._raise_error = raise_error

    async def __aenter__(self):
        """Enter the response context."""
        return self

    async def __aexit__(self, exc_type, exc, tb):
        """Exit the response context."""
        return None

    async def json(self, content_type=None):
        """Return JSON payload."""
        return self._json_data

    def raise_for_status(self):
        """Raise a configured HTTP error."""
        if self._raise_error is not None:
            raise self._raise_error


def test_normalize_base_url():
    """Test Domoticz URL normalization."""
    assert normalize_base_url("192.168.1.20:8080") == "http://192.168.1.20:8080"
    assert (
        normalize_base_url("https://domoticz.local:8443/some/path?x=1")
        == "https://domoticz.local:8443/some/path"
    )
    assert (
        normalize_base_url("https://domoticz.local:8443/some/path/json.htm")
        == "https://domoticz.local:8443/some/path"
    )
    assert (
        normalize_base_url("https://domoticz.local:8443/json.htm")
        == "https://domoticz.local:8443"
    )
    assert (
        normalize_base_url("https://domoticz.example.com:8443/domoticz")
        == "https://domoticz.example.com:8443/domoticz"
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://embedded-user@domoticz.local",
        "http://embedded-user:embedded-value@domoticz.local",
    ],
)
def test_normalize_base_url_rejects_embedded_credentials(url):
    """Credentials must use the dedicated fields and never enter URLs."""
    with pytest.raises(DomoticzApiError, match="must not contain"):
        normalize_base_url(url)


def test_get_devices_sends_expected_params():
    """Test getdevices request and response parsing."""
    session = MagicMock()
    session.get.return_value = MockResponse(
        json_data={
            "status": "OK",
            "result": [
                {"idx": "1", "Name": "Kitchen", "Type": "Temp", "Temp": 19.5},
                {"Name": "Ignored without idx"},
            ],
        }
    )
    api = DomoticzApi(
        session,
        "http://domoticz.local:8080",
        "test-user",
        "test-password",
    )

    devices = asyncio.run(
        api.async_get_devices(include_hidden=True, favorite_only=True)
    )

    assert len(devices) == 1
    assert devices[0].idx == "1"
    url = session.get.call_args.args[0]
    kwargs = session.get.call_args.kwargs
    assert url == "http://domoticz.local:8080/json.htm"
    assert kwargs["params"]["param"] == "getdevices"
    assert kwargs["params"]["displayhidden"] == "1"
    assert kwargs["params"]["favorite"] == "1"
    assert "auth" not in kwargs
    headers = kwargs["headers"]
    assert set(headers) == {"Authorization"}
    expected_header = "Basic " + b64encode(
        b"test-user:test-password",
    ).decode("ascii")
    if not compare_digest(
        headers["Authorization"],
        expected_header,
    ):
        raise AssertionError("Authorization header encoding mismatch")


def test_get_server_time_auth_error():
    """Test HTTP auth failures are classified."""
    session = MagicMock()
    session.get.return_value = MockResponse(status=401)
    api = DomoticzApi(session, "http://domoticz.local:8080")

    try:
        asyncio.run(api.async_get_server_time())
    except DomoticzAuthError:
        kwargs = session.get.call_args.kwargs
        assert "auth" not in kwargs
        assert kwargs["headers"] is None
        return
    raise AssertionError("Expected DomoticzAuthError")


def test_http_errors_are_connection_errors():
    """Test non-auth HTTP failures are classified as connection errors."""
    session = MagicMock()
    error = ClientResponseError(None, (), status=500)
    session.get.return_value = MockResponse(status=500, raise_error=error)
    api = DomoticzApi(session, "http://domoticz.local:8080")

    try:
        asyncio.run(api.async_get_server_time())
    except DomoticzConnectionError:
        return
    raise AssertionError("Expected DomoticzConnectionError")


def test_domoticz_application_error():
    """Test Domoticz ERROR payloads are classified."""
    session = MagicMock()
    session.get.return_value = MockResponse(
        json_data={"status": "ERROR", "message": "Bad request"}
    )
    api = DomoticzApi(session, "http://domoticz.local:8080")

    try:
        asyncio.run(api.async_get_server_time())
    except DomoticzApiError:
        return
    raise AssertionError("Expected DomoticzApiError")


def test_switch_command_success():
    """Test switch command transmits expected URL parameters."""
    session = MagicMock()
    session.get.return_value = MockResponse(
        json_data={"status": "OK", "title": "SwitchLight"}
    )
    api = DomoticzApi(session, "http://domoticz.local:8080")

    asyncio.run(api.async_switch_command("42", "On"))

    kwargs = session.get.call_args.kwargs
    params = kwargs["params"]
    assert params["param"] == "switchlight"
    assert params["idx"] == "42"
    assert params["switchcmd"] == "On"


def test_switch_command_validation():
    """Test switch command rejects invalid command and empty idx."""
    session = MagicMock()
    api = DomoticzApi(session, "http://domoticz.local:8080")

    with pytest.raises(DomoticzApiError, match="Invalid switch command"):
        asyncio.run(api.async_switch_command("42", "Invalid"))

    with pytest.raises(DomoticzApiError, match="Invalid device idx"):
        asyncio.run(api.async_switch_command("", "On"))


def test_set_level_command():
    """Test set level command transmits rounded percentage level."""
    session = MagicMock()
    session.get.return_value = MockResponse(
        json_data={"status": "OK", "title": "SwitchLight"}
    )
    api = DomoticzApi(session, "http://domoticz.local:8080")

    asyncio.run(api.async_set_level("42", 75.4))

    kwargs = session.get.call_args.kwargs
    params = kwargs["params"]
    assert params["param"] == "switchlight"
    assert params["idx"] == "42"
    assert params["switchcmd"] == "Set Level"
    assert params["level"] == "75"


def test_set_level_clamping():
    """Test set level clamps values outside 0-100."""
    session = MagicMock()
    session.get.return_value = MockResponse(
        json_data={"status": "OK", "title": "SwitchLight"}
    )
    api = DomoticzApi(session, "http://domoticz.local:8080")

    asyncio.run(api.async_set_level("42", 150))
    assert session.get.call_args.kwargs["params"]["level"] == "100"

    asyncio.run(api.async_set_level("42", -20))
    assert session.get.call_args.kwargs["params"]["level"] == "0"


def test_set_color_command():
    """Test set color transmits JSON color structure and brightness."""
    session = MagicMock()
    session.get.return_value = MockResponse(
        json_data={"status": "OK", "title": "SetColBrightnessValue"}
    )
    api = DomoticzApi(session, "http://domoticz.local:8080")

    asyncio.run(api.async_set_color("42", rgb=(255, 128, 0), brightness=80))

    kwargs = session.get.call_args.kwargs
    params = kwargs["params"]
    assert params["param"] == "setcolbrightnessvalue"
    assert params["idx"] == "42"
    assert params["brightness"] == "80"
    assert (
        '{"m": 3, "t": 0, "r": 255, "g": 128, "b": 0, "cw": 0, "ww": 0}'
        in params["color"]
    )


def test_set_color_pure_brightness_fallback():
    """Test set color with only brightness delegates to set level."""
    session = MagicMock()
    session.get.return_value = MockResponse(
        json_data={"status": "OK", "title": "SwitchLight"}
    )
    api = DomoticzApi(session, "http://domoticz.local:8080")

    asyncio.run(api.async_set_color("42", brightness=60))

    kwargs = session.get.call_args.kwargs
    params = kwargs["params"]
    assert params["param"] == "switchlight"
    assert params["switchcmd"] == "Set Level"
    assert params["level"] == "60"


def test_blind_command():
    """Test blind control actions."""
    session = MagicMock()
    session.get.return_value = MockResponse(
        json_data={"status": "OK", "title": "SwitchLight"}
    )
    api = DomoticzApi(session, "http://domoticz.local:8080")

    asyncio.run(api.async_blind_command("42", "Open"))
    assert session.get.call_args.kwargs["params"]["switchcmd"] == "Open"

    asyncio.run(api.async_blind_command("42", "Close"))
    assert session.get.call_args.kwargs["params"]["switchcmd"] == "Close"

    asyncio.run(api.async_blind_command("42", "Stop"))
    assert session.get.call_args.kwargs["params"]["switchcmd"] == "Stop"

    with pytest.raises(DomoticzApiError, match="Invalid blind action"):
        asyncio.run(api.async_blind_command("42", "Jump"))


def test_scene_command():
    """Test scene activation."""
    session = MagicMock()
    session.get.return_value = MockResponse(
        json_data={"status": "OK", "title": "SwitchScene"}
    )
    api = DomoticzApi(session, "http://domoticz.local:8080")

    asyncio.run(api.async_scene_command("5", "On"))

    kwargs = session.get.call_args.kwargs
    params = kwargs["params"]
    assert params["param"] == "switchscene"
    assert params["idx"] == "5"
    assert params["switchcmd"] == "On"


def test_timeout_classified_as_domoticz_timeout_error():
    """Test timeout error is classified as DomoticzTimeoutError."""
    session = MagicMock()
    session.get.side_effect = TimeoutError("Connection timed out")
    api = DomoticzApi(session, "http://domoticz.local:8080")

    with pytest.raises(DomoticzTimeoutError, match="Timed out"):
        asyncio.run(api.async_get_server_time())


def test_device_unavailable_classified_as_domoticz_device_unavailable_error():
    """Test Domoticz error for unknown idx is classified as device unavailable."""
    session = MagicMock()
    session.get.return_value = MockResponse(
        json_data={"status": "ERROR", "message": "Device not found for idx: 999"}
    )
    api = DomoticzApi(session, "http://domoticz.local:8080")

    with pytest.raises(DomoticzDeviceUnavailableError, match="Device not found"):
        asyncio.run(api.async_switch_command("999", "On"))
