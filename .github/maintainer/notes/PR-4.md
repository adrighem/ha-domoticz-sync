# PR:4 - actions/checkout v7

## Snapshot

- Title: `chore(deps): bump actions/checkout from 4 to 7 in the github-actions group`
- Author: Dependabot
- State: Open, mergeable
- Scope: `.github/workflows/hacs-validation.yml`, `.github/workflows/hassfest.yml`

## Intent

Keep GitHub workflow dependencies current by updating `actions/checkout` from `v4`
to `v7`.

## Assessment

- Low-risk maintenance update: only two workflow checkout steps change.
- All PR checks passed on GitHub: CI, CodeQL, dependency review, HACS validation,
  hassfest, and pip-audit.
- Local equivalent patch prepared instead of merging the bot branch, matching the
  standing rule for Dependabot PRs.
- User approved public action on 2026-07-06.

## Verification

- `python -m pytest` - 16 passed
- `uvx ruff check .` - passed
- Post-push GitHub Actions for `42c30d9` all passed: CI, CodeQL, HACS
  Validation, Validate with hassfest, Python Dependency Audit, and Release
  Please.

## Outcome

- Applied the equivalent update directly on `main` in `42c30d9`.
- Closed `PR:4` with a short public note explaining that the update landed on
  `main`.
- Final overview found no unread notifications, open issues, open PRs,
  Dependabot alerts, or code scanning alerts.
