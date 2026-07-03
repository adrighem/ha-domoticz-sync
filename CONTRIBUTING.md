# Contributing

Thanks for helping improve Domoticz Import.

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

## Commits

Use Conventional Commit prefixes so Release Please can prepare releases:

- `fix:` for bug fixes
- `feat:` for user-visible functionality
- `docs:` for documentation-only changes
- `test:` for test-only changes
- `chore:` for maintenance work

Use `!` or a `BREAKING CHANGE:` footer for breaking changes.
