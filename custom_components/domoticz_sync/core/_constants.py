"""Protocol constants, feature flags, wire limits, and schema keys.

The module is deliberately host-neutral and uses only Python 3.9-compatible
standard-library features.
"""

from __future__ import annotations

PROTOCOL_VERSION_V1 = 1
PROTOCOL_VERSION = PROTOCOL_VERSION_V1
PROTOCOL_VERSION_V2 = 2

WEBSOCKET_SUBPROTOCOL_V2 = "ha-domoticz-sync.v2"
FEATURE_DOMOTICZ_INVENTORY_V1 = "domoticz-inventory.v1"
FEATURE_HA_EXPORT_BINARY_V1 = "ha-export.binary.v1"
FEATURE_HA_EXPORT_CONTINUOUS_V1 = "ha-export.continuous.v1"
FEATURE_HA_EXPORT_NUMERIC_V1 = "ha-export.numeric.v1"
FEATURE_DOMOTICZ_CONTROL_V1 = "domoticz-control.v1"

SUPPORTED_WEBSOCKET_SUBPROTOCOLS = (WEBSOCKET_SUBPROTOCOL_V2,)
SUPPORTED_V2_FEATURES = (
    FEATURE_DOMOTICZ_CONTROL_V1,
    FEATURE_DOMOTICZ_INVENTORY_V1,
    FEATURE_HA_EXPORT_BINARY_V1,
    FEATURE_HA_EXPORT_CONTINUOUS_V1,
    FEATURE_HA_EXPORT_NUMERIC_V1,
)

DIRECTION_DOMOTICZ_TO_HA = "domoticz_to_home_assistant"
DIRECTION_HA_TO_DOMOTICZ = "home_assistant_to_domoticz"

PAIRING_KEY_BITS = 256
NONCE_BITS = 256
MAX_MESSAGE_BYTES = 64 * 1024
MAX_JSON_DEPTH = 32
MAX_SAFE_INTEGER = 9_007_199_254_740_991
MAX_SEQUENCE = MAX_SAFE_INTEGER
MAX_PROTOCOL_TOKENS = 16
MAX_FEATURE_IDS = 64
MAX_INVENTORY_TARGETS = 512
MAX_INVENTORY_UNITS = 1024
MAX_INVENTORY_PAGES = 512
MAX_INVENTORY_TARGETS_PER_PAGE = 64
MAX_INVENTORY_PAYLOAD_BYTES = 60 * 1024
INVENTORY_TIMEOUT_SECONDS = 10
MAX_INVENTORY_TARGET_ID_BYTES = 128
MAX_INVENTORY_NAME_BYTES = 512
MAX_INVENTORY_S_VALUE_BYTES = 4096
MAX_INVENTORY_OPTION_BYTES = 1024

_HELLO_KEYS = {"version", "type", "link_id", "destination_id", "client_nonce"}
_CHALLENGE_KEYS = {"version", "type", "server_nonce", "server_proof"}
_AUTHENTICATE_KEYS = {"version", "type", "client_proof"}
_READY_KEYS = {"version", "type", "session_id"}
_V2_HELLO_KEYS = {
    "version",
    "type",
    "link_id",
    "destination_id",
    "client_nonce",
    "client_protocols",
    "selected_protocol",
    "client_features",
}
_V2_CHALLENGE_KEYS = {
    "version",
    "type",
    "server_nonce",
    "server_protocols",
    "selected_protocol",
    "server_features",
    "selected_features",
    "server_proof",
}
_APPLICATION_READY_KEYS = {"schema", "type"}
_APPLY_KEYS = {"schema", "type", "request_id", "action"}
_APPLY_RESULT_KEYS = {
    "schema",
    "type",
    "request_id",
    "status",
    "target_id",
    "source",
}
_INVENTORY_REQUEST_KEYS = {"schema", "type", "request_id"}
_INVENTORY_RESULT_KEYS = {
    "schema",
    "type",
    "request_id",
    "status",
    "page",
    "complete",
    "targets",
}
_INVENTORY_TARGET_KEYS = {"target_id", "timed_out", "units"}
_INVENTORY_UNIT_KEYS = {
    "unit",
    "name",
    "type",
    "subtype",
    "switch_type",
    "used",
    "n_value",
    "s_value",
    "custom_option",
    "has_other_options",
}
_ACTION_KEYS = {"kind", "capability", "target_id", "stale"}
_CAPABILITY_KEYS = {
    "source",
    "kind",
    "name",
    "value",
    "availability",
    "semantic",
    "unit",
    "state_class",
    "options",
}
_COMPOUND_CAPABILITY_KEYS = {
    "source",
    "kind",
    "name",
    "availability",
    "capabilities",
}
_CONTROL_REQUEST_KEYS = {
    "schema",
    "type",
    "request_id",
    "target_id",
    "unit",
    "command",
    "level",
    "color",
}
_CONTROL_RESULT_KEYS = {"schema", "type", "request_id", "status", "error"}
_SOURCE_KEYS = {"system", "instance_id", "object_id", "capability_id"}
_ENVELOPE_KEYS = {
    "version",
    "type",
    "session_id",
    "direction",
    "sequence",
    "payload",
    "signature",
}

__all__ = [
    "DIRECTION_DOMOTICZ_TO_HA",
    "DIRECTION_HA_TO_DOMOTICZ",
    "FEATURE_DOMOTICZ_CONTROL_V1",
    "FEATURE_DOMOTICZ_INVENTORY_V1",
    "FEATURE_HA_EXPORT_BINARY_V1",
    "FEATURE_HA_EXPORT_CONTINUOUS_V1",
    "FEATURE_HA_EXPORT_NUMERIC_V1",
    "INVENTORY_TIMEOUT_SECONDS",
    "MAX_FEATURE_IDS",
    "MAX_INVENTORY_NAME_BYTES",
    "MAX_INVENTORY_OPTION_BYTES",
    "MAX_INVENTORY_PAGES",
    "MAX_INVENTORY_PAYLOAD_BYTES",
    "MAX_INVENTORY_S_VALUE_BYTES",
    "MAX_INVENTORY_TARGET_ID_BYTES",
    "MAX_INVENTORY_TARGETS",
    "MAX_INVENTORY_TARGETS_PER_PAGE",
    "MAX_INVENTORY_UNITS",
    "MAX_JSON_DEPTH",
    "MAX_MESSAGE_BYTES",
    "MAX_PROTOCOL_TOKENS",
    "MAX_SAFE_INTEGER",
    "MAX_SEQUENCE",
    "NONCE_BITS",
    "PAIRING_KEY_BITS",
    "PROTOCOL_VERSION",
    "PROTOCOL_VERSION_V1",
    "PROTOCOL_VERSION_V2",
    "SUPPORTED_V2_FEATURES",
    "SUPPORTED_WEBSOCKET_SUBPROTOCOLS",
    "WEBSOCKET_SUBPROTOCOL_V2",
    "_ACTION_KEYS",
    "_APPLICATION_READY_KEYS",
    "_APPLY_KEYS",
    "_APPLY_RESULT_KEYS",
    "_AUTHENTICATE_KEYS",
    "_CAPABILITY_KEYS",
    "_CHALLENGE_KEYS",
    "_COMPOUND_CAPABILITY_KEYS",
    "_CONTROL_REQUEST_KEYS",
    "_CONTROL_RESULT_KEYS",
    "_ENVELOPE_KEYS",
    "_HELLO_KEYS",
    "_INVENTORY_REQUEST_KEYS",
    "_INVENTORY_RESULT_KEYS",
    "_INVENTORY_TARGET_KEYS",
    "_INVENTORY_UNIT_KEYS",
    "_READY_KEYS",
    "_SOURCE_KEYS",
    "_V2_CHALLENGE_KEYS",
    "_V2_HELLO_KEYS",
]
