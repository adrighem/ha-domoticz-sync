# Maintainer Decisions

## 2026-07-03

- Use `domoticz_import` as the Home Assistant domain to avoid colliding with existing or reserved domains.
- Keep the first version read-only to reduce user risk and narrow the support surface.
- License the repository as GPL-3.0-only.
- Use Release Please with Conventional Commits for changelog, version bump, tag, and GitHub Release automation.
- Use Dependabot PRs as input and apply accepted dependency updates directly rather than merging bot branches.
