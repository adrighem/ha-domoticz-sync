# Maintainer Decisions

## 2026-07-03

- Use `domoticz_sync` as the Home Assistant domain to avoid colliding with existing or reserved domains.
- Keep the first version read-only to reduce user risk and narrow the support surface.
- License the repository as GPL-3.0-only.
- Use Release Please with Conventional Commits for changelog, version bump, tag, and GitHub Release automation.
- Use Dependabot PRs as input and apply accepted dependency updates directly rather than merging bot branches.

## 2026-07-09

- Keep HACS validation blocking on push and pull requests, but make the daily scheduled run less prone to upstream raw-content rate limits by using explicit read-only token permissions and a staggered cron.
- Disable automated HACS PR comments so validation feedback stays in GitHub checks unless a maintainer explicitly chooses to comment.

## 2026-09-13

- Support bidirectional control for imported Domoticz switches, relays, outlets, and push buttons in Home Assistant with optimistic UI state and error rollback.
- Support reverse control for exported Home Assistant switches, lights, covers, and buttons from Domoticz via authenticated HMAC-SHA256 protocol envelopes.
- Enforce loop safety via `is_domoticz_mirror` provenance filtering in `home_assistant_source.py`, preventing circular export ping-pong.
- Enforce sliding-window rate limiting (30 commands per 5-second window) and in-flight request deduplication on the export bridge to protect Home Assistant from command bursts.
- Domoticz plugin captures unit state prior to control actions and executes automatic UI rollback on rejection to eliminate bounce.
