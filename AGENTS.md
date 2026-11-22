# AGENTS.md

Guide for coding agents and new contributors. Fullstack Food monitors and controls
small indoor growing setups (house plants, microgreens, mushrooms) on a local network.

## State of the repo

Prototype, mid-restructure. `docs/plan/restructure-plan.md` is the roadmap and
describes the target layout; phase 0 (hygiene) is done, later phases are not.
Until phase 2 lands, code lives in the legacy layout below.

| Path | What it is |
|---|---|
| `iot-manager/` | Hub prototype: Redis/RQ scheduler and worker, SQLite datastore, device classes, Flask + Vue dashboard |
| `iot-manager/devices/tests/` | Bench scripts for individual sensors (need real hardware) |
| `iot-manager/config/` | Device and protocol YAML (to be replaced by `catalog/` and `sites/`) |
| `copilot/` | Garden copilot stubs |
| `nodes/` | MCU firmware (CircuitPython) and SBC setup notes |
| `electronics/` | KiCad project |
| `homeassistant/` | Home Assistant Core config and requirements |
| `sites/local/` | Gitignored. Your real site config and `secrets.yaml` |

## Commands

- `just lint` runs `ruff check .` (CI runs the same).
- `just test` runs pytest on `iot-manager/tests`. The existing tests are stubs.

## Rules

- Never commit secrets, IP addresses of real devices, WiFi credentials, API keys or
  webhook ids. Local values go in `sites/local/secrets.yaml`; code reads them from
  environment variables or a gitignored file, and a `*.example.*` file documents the keys.
- Never commit databases, logs, photos or firmware binaries. They are gitignored;
  binaries are published as release assets.
- No machine-specific absolute paths in code or docs.
- Python 3.12. Lint rules are in `pyproject.toml`.
