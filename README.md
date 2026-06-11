# Dell 7609WU Projector — Home Assistant integration

[![Validate](https://github.com/CaelanBorowiec/ha-dell-projector-network-control/actions/workflows/validate.yml/badge.svg)](https://github.com/CaelanBorowiec/ha-dell-projector-network-control/actions/workflows/validate.yml)
[![Lint](https://github.com/CaelanBorowiec/ha-dell-projector-network-control/actions/workflows/lint.yml/badge.svg)](https://github.com/CaelanBorowiec/ha-dell-projector-network-control/actions/workflows/lint.yml)
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

Control and monitor **Dell 7609WU** projectors over the network from Home
Assistant, using the projector's built-in web management interface (no RS232
cable needed). Dell never documented this HTTP interface — it was
reverse-engineered for this project; see [`docs/PROTOCOL.md`](docs/PROTOCOL.md).

## Features

Per projector (multiple projectors supported, one config entry each):

| Entity | Type | Notes |
|---|---|---|
| Power | switch | Power ON / Power OFF |
| Blank screen | switch | hide/show the image |
| ECO mode | switch | ECO vs Full Power lamp mode |
| Source | select | VGA-A/B, S-Video, Composite, Component, DisplayPort, HDMI-A/B |
| Video mode | select | Presentation, Bright, Movie, sRGB, Custom |
| Aspect ratio | select | 1:1, 4:3, 16:9 |
| Projection mode | select | front/rear, desktop/ceiling |
| Power saving timeout | select | Off – 120 min |
| Brightness / Contrast | number | 0–100 |
| Volume | number | 0–20 |
| Status | sensor | Lamp ON, Standby, Warm up, Cooling, Power Saving |
| Lamp hours | sensor | total lamp runtime |
| Error status | sensor | diagnostic |
| Firmware version | sensor | diagnostic, disabled by default |
| Auto adjust | button | trigger source auto-adjustment |

- **Authentication**: supported per device. The projector's username is fixed
  to `administrator` by firmware; if an admin password is enabled in the
  projector's web management, enter it during setup. Includes reauth (HA will
  prompt if the password changes) and reconfigure flows.
- **Discovery**: projectors may be discovered via DHCP (Dell OUI match plus a
  probe of the web interface). Manual setup by IP is always available.
- **Local polling** every 30 seconds; commands trigger an immediate refresh.

## Installation

### HACS (custom repository)

1. HACS → menu (⋮) → *Custom repositories*.
2. Add `https://github.com/CaelanBorowiec/ha-dell-projector-network-control`
   with category **Integration**.
3. Install **Dell 7609WU Projector**, then restart Home Assistant.

### Manual

Copy `custom_components/dell_7609wu/` into your Home Assistant
`config/custom_components/` directory and restart.

## Configuration

1. Settings → Devices & Services → **Add Integration** → *Dell 7609WU Projector*.
2. Enter the projector's IP address (e.g. `10.10.0.227`).
3. If the projector has an admin password enabled, enter it (username is fixed
   to `administrator`). Leave empty otherwise.

Repeat for each projector.

## Repository contents

| Path | Purpose |
|---|---|
| `custom_components/dell_7609wu/` | the Home Assistant integration |
| `docs/PROTOCOL.md` | reverse-engineered HTTP API reference for the 7609WU |
| `tools/api-tester.html` | standalone live test UI — open in a browser, point it at a projector, and fire raw commands |
| `tools/smoke_test.py` | standalone CLI test of the API client (`python tools/smoke_test.py <ip> [--password X] [--command]`) |

## Notes & limitations

- The 7609WU's web server is HTTP/1.0 from 2008: one session cookie (`ATOP`),
  HTML scraping for state, and full-form posts for commands. The integration
  faithfully replays browser behavior; see the protocol doc before changing
  payload handling.
- Power state reports the firmware's own status text. After Power ON/OFF the
  projector goes through *Warm up*/*Cooling*, visible in the Status sensor.
- The projector password is limited to 4 characters by the firmware and the
  login uses unsalted MD5 — treat it as a convenience lock, not security.
- Inclusion in the HACS **default** store would additionally require a
  [home-assistant/brands](https://github.com/home-assistant/brands) logo PR and
  repository description/topics on GitHub. Until then, install as a custom
  repository (above).

## Development

```bash
python -m venv .venv
.venv/Scripts/pip install aiohttp ruff          # Windows
ruff check custom_components tools
python tools/smoke_test.py 10.10.0.227 --command
```

CI runs [HACS validation](https://github.com/hacs/action),
[hassfest](https://github.com/home-assistant/actions) and ruff on every push.
