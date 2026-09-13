# Contributing

Thanks for helping improve Domoticz Sync.

## Development

Install development dependencies:

```bash
python -m pip install -e ".[test,lint,security]"
```

Run the checks before opening a pull request:

```bash
python -m ruff check .
python -m pytest
python -m compileall custom_components tests
```

## Bidirectional Sync Safety Requirements

When adding or modifying device types, entity platforms, or export/import pipelines, contributors must satisfy the following safety rules:

1. **Loop Prevention & Provenance**:
   - Entities imported from Domoticz carry `domoticz_sync_origin: "domoticz"` attributes.
   - Any entity flagged by `is_sync_plugin_device` or originating from Domoticz must be excluded from export selection with reason `DOMOTICZ_MIRROR` in `home_assistant_source.py`.
   - Never allow an imported entity to be echoed back to the originating system.

2. **Authenticated Protocol & Signature Verification**:
   - All reverse control payloads between Domoticz and Home Assistant must use signed HMAC-SHA256 protocol envelopes.
   - Sequence tracking and timestamp validation prevent replay and packet injection attacks.

3. **Rate Limiting & Command Deduplication**:
   - The export bridge must throttle incoming command bursts (sliding-window rate limiter) and deduplicate in-flight requests by `request_id`.

4. **Optimistic Hold & Rejection Rollback**:
   - Home Assistant controllable platforms must use optimistic state holds to eliminate UI toggle bounce during coordinator polling intervals.
   - The Domoticz companion plugin must capture prior unit state and roll back automatically when a command is rejected by Home Assistant.

5. **Python 3.9 & Host Neutrality**:
   - Shared core protocol modules (`core/protocol.py`) and `plugin.py` must maintain strict Python 3.9 compatibility (no union `|` syntax) and zero third-party dependencies outside standard library and `DomoticzEx`.

## Commits

Use Conventional Commit prefixes so Release Please can prepare releases:

- `fix:` for bug fixes
- `feat:` for user-visible functionality
- `docs:` for documentation-only changes
- `test:` for test-only changes
- `chore:` for maintenance work

Use `!` or a `BREAKING CHANGE:` footer for breaking changes.
