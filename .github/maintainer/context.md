# Maintainer Context

## Project

Domoticz Sync is a Home Assistant custom integration and companion Domoticz plugin that provides bidirectional state synchronization and safe cross-system control.

## Priorities

- Keep the integration safe, robust, and predictable for Home Assistant and Domoticz users.
- Expand Domoticz device coverage based on real samples and focused parser tests.
- Enforce strict bidirectional loop safety, provenance validation (`is_domoticz_mirror`), rate limiting, and optimistic state rollback.
- Prefer small, well-tested changes over broad rewrites.

## Tone

Friendly, concise, and practical. Public replies should answer the topic directly and avoid unnecessary process detail.

## Boundaries

- Do not request or store live Domoticz credentials.
- Do not merge external pull requests directly; use them as implementation input.
- Public actions require explicit approval.
