<p align="center">
  <img src="assets/app-icon-1254.png" alt="Domoticz Sync app icon" width="160">
</p>

# Domoticz Sync for Home Assistant

[![CI](https://github.com/adrighem/ha-domoticz-sync/actions/workflows/ci.yml/badge.svg)](https://github.com/adrighem/ha-domoticz-sync/actions/workflows/ci.yml)
[![CodeQL](https://github.com/adrighem/ha-domoticz-sync/actions/workflows/codeql.yml/badge.svg)](https://github.com/adrighem/ha-domoticz-sync/actions/workflows/codeql.yml)

This custom integration syncs device state from Domoticz into Home Assistant using the Domoticz JSON API.

It is intentionally read-only for the first version:

- Polls `/json.htm?type=command&param=getdevices&filter=all&used=true&order=Name`
- Creates Home Assistant sensors for typed Domoticz values such as temperature, humidity, pressure, power, counters, rain, wind, battery, and text values
- Creates read-only binary sensors for Domoticz switch/security states such as motion, door contact, smoke, moisture, and on/off switches
- Supports username/password Basic Auth
- Supports hidden-device and favorite-only filters through the options flow

## Installation

Copy `custom_components/domoticz_sync` into your Home Assistant `custom_components` directory and restart Home Assistant.

Then go to **Settings** -> **Devices & services** -> **Add integration** and search for **Domoticz Sync**.

## Configuration

The setup flow asks for:

- Domoticz URL, for example `http://192.168.1.20:8080`
- Username and password, if your Domoticz instance requires them
- SSL verification for HTTPS Domoticz installations

Options:

- Include hidden devices
- Only import favorite devices
- Polling interval in seconds

## Development

Run tests from this folder:

```bash
python -m pytest
```

The parser and API client are split from Home Assistant entity code so support for more Domoticz device types can be added with focused tests.

Releases are managed by Release Please. Use Conventional Commit messages such as `fix:` and `feat:` for user-visible changes.

## Security

CodeQL, Dependency Review, pip-audit, and Dependabot are configured for this repository. Please report vulnerabilities privately through GitHub Security Advisories and do not include secrets in public issues.

## License

GPL-3.0-only. See [LICENSE](LICENSE).
