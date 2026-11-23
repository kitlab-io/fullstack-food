# AGENTS.md

Guide for coding agents and new contributors. Fullstack Food monitors and controls
small indoor growing setups (house plants, microgreens, mushrooms) on a local network.

## State of the repo

Mid-restructure. `docs/plan/restructure-plan.md` is the roadmap. Done so far: phase 0
(hygiene), phase 1 (schemas and catalog), phase 2 (hub, simulator, scenario tests) and
the status/LED engine from phase 3. Two follow-on plans are under way:
`docs/plan/dashboard-plan.md` D1 to D4 (hub groundwork, dashboard, log and raw data, login
and actions), and `docs/plan/installation-plan.md` I1 (assembly and test data per part, pin
validation), the software halves of I2 (ESPHome config generation, node contract suite) and
I3 (observe mode, commissioning records, bench, calibration and zone acceptance tools), and
I4 (generated BOM, wiring diagrams, build guide, checklist and LED legend).
Nothing has run on real hardware yet: no pin, wiring or power value in the catalog has been
confirmed on a bench (`datasheet_checked: false`), and the generated firmware compiles with
ESPHome but has never been flashed.

## Layout

| Path | What it is |
|---|---|
| `schemas/` | JSON Schema for every YAML kind and for MQTT payloads (`schemas/mqtt/`). Source of truth. |
| `catalog/components/` | Generic capabilities, e.g. `sensor.soil_moisture`, `actuator.pump` |
| `catalog/models/` | Exact parts, what they implement, drivers and how well each is tested |
| `catalog/boards/`, `species/`, `recipes/`, `goals/`, `themes/` | Boards, plants/fungi, climate recipes, goal overlays, LED status themes |
| `sites/examples/<name>/` | `site.yaml` (nodes, devices, zones, plantings) and `sim.yaml` (simulated environment) |
| `sites/local/` | Gitignored. A real site and its `secrets.yaml` |
| `packages/core/fsf_core` | Loading and validation, recipe layering, pin checks, bus, clock, topic contract |
| `packages/hub/fsf_hub` | Control loops, safety limits, operator commands, zone status, LED rendering, SQLite store with retention |
| `packages/core/fsf_core/firmware` | ESPHome config generation from a site file; `fsf_node.h` is the C++ shared by every node |
| `packages/core/fsf_core/builddocs.py` | Generated build documents: BOM, power budget, wiring SVG, build guide, checklist, LED legend |
| `packages/core/fsf_core/nodetest.py` | Node contract suite, run against simulated or real nodes |
| `packages/hub/fsf_hub/commissioning.py` | Bench test, calibration and zone acceptance, driven over MQTT and recorded by the hub |
| `packages/sim/fsf_sim` | Simulated nodes, zone physics, fault injection, `MockSystem` test harness |
| `packages/web/fsf_web` | Dashboard service: FastAPI over the hub database and live MQTT state, shared login, actions sent as hub commands |
| `packages/web/frontend` | Dashboard frontend (Vue 3, Vite, uPlot), built to `dist/` and served by `fsf_web` |
| `tests/unit`, `tests/contract`, `tests/system`, `tests/web` | Core logic, MQTT and node contract, scenario tests, dashboard API |
| `tests/browser` | Playwright test driving a mushroom grow through the dashboard; skipped unless `FSF_BROWSER_URL` is set |
| `tests/hil` | The node contract suite against a real bench rig; skipped unless `FSF_HIL_SITE` and `FSF_HIL_MQTT_HOST` are set |
| `deploy/` | Dockerfile and compose files: broker, hub, dashboard, and the simulator for the mock stack |
| `iot-manager/`, `copilot/`, `nodes/`, `electronics/`, `homeassistant/` | Legacy prototype, kept for reference until later phases replace it. Do not extend it. |

## Commands

```
just validate          # catalog + example sites against the schemas
just validate --pins   # also propose board pins for devices that have none assigned
just test              # all tests, about three minutes
just firmware sites/examples/houseplants --include-sim    # ESPHome configs into build/firmware/
just node-test shelf-node --site <site> --actuate         # contract suite against a real broker
just docs sites/examples/houseplants    # BOM, wiring, build guide, checklist, legend into build/docs/
just web-build         # build the dashboard frontend (needs Node.js)
just lint              # ruff, same as CI
just mock mushrooms 600   # simulated site against a real Mosquitto broker in Docker, 600x speed;
                          # dashboard on http://localhost:8080
just mock-watch        # tail every MQTT message of the running mock stack
```

Without `just`/`uv`: `pip install -e ".[web]" pytest ruff httpx`, then `fsf validate` (or
`python -m fsf_core validate`), `pytest`, `ruff check .`. The dashboard tests are skipped
without FastAPI, and the ESPHome validation test without the `esphome` command.

## How the pieces fit

- Nodes and the hub talk only over MQTT. Topics are in `packages/core/fsf_core/topics.py`,
  payloads in `schemas/mqtt/`. A simulated node and a real one must be indistinguishable.
- The hub is driven by `Hub.tick()` with an injected clock and bus. It owns no threads.
  Scenario tests run it on `InMemoryBus` + `VirtualClock`; the mock stack and real
  deployments use `MqttBus`.
- A zone runs the current recipe stage of the planting located in it. Setpoints resolve as
  species defaults -> recipe stage -> goal overlay -> planting overrides (`fsf_core/recipes.py`).
- Every actuator on-command carries `duration_s` (a lease). The hub renews it while it wants
  the actuator on; the node switches off when it expires. Never add an unbounded on-command.
- People act through hub commands on `fsf/<site>/hub/cmd` (`advance_stage`, `water_now`,
  `set_override`, `clear_override`, `pause_zone`, `resume_zone`, `actuator_test`); the hub
  answers on `hub/reply` with the same `id`. Nothing but the hub publishes to device topics.
  A paused zone and a timed override survive a hub restart.
- The hub records why each control loop is on or off in the decision trace (one row per
  change of decision, not per tick), every device command with its ack, and events with a
  level. Raw readings, trace and commands age out (`retention` in the site file); 5-minute and
  hourly rollups and events are kept. A retained `hub/state` carries plantings and actuators.
- A zone in observe mode computes and logs every decision but sends nothing to its
  actuators. An operator can set it (`set_zone_mode`), and a zone with a real (non-simulated)
  actuator that has not passed a bench test is in it automatically. Dose and limit events
  from an observing zone carry `observed: true`. `actuator_test` still works there.
- Commissioning goes bench (`fsf bench`), calibration (`fsf calibrate`), `fsf node test`,
  observe, `fsf zone test`, then `fsf zone mode <zone> active`. The tools record results with
  the hub's `commission` command; they never write the database or the site file.
- A node may send anything: the hub ignores a payload that is not a JSON object and logs
  `bad_payload` once per topic.
- The dashboard opens the hub's SQLite file read-only and subscribes to MQTT. Its one way
  to change anything is `POST /api/commands`, which publishes a hub command and returns the
  hub's reply; it never writes the database or publishes to a device topic. Everything needs
  the shared login (scrypt hash in `FSF_WEB_PASSWORD_HASH`, made with
  `python -m fsf_web hash-password`) unless `--read-without-login` or, for the mock stack
  only, `--no-login`. State-changing requests also need the session's CSRF token.
- Build documents are generated from the site file and the catalog (`fsf docs build`); fix
  the catalog or the site, never the generated file. Status labels and meanings live in the
  theme and are used by both the legend card and the dashboard.
- Firmware is generated, never hand-edited: device blocks come from the ESPHome driver
  `template` of each model, the contract parts (status as birth and last will, leases that
  the node ends itself, acks) from `fsf_core/firmware`. Soil probes sit on an I2C ADC
  (`pins: { adc: soil-adc/A0 }`), which keeps the example builds within the board's pins.
- Zone status comes from recipe target bands (debounced), alerts (immediate), and safety
  conditions (`offline`, `sensor_stale`, `reservoir_low`). The theme's `priority` list picks
  which one the LED segment shows.

## Common tasks

- **Add a part**: new file in `catalog/models/`, `implements` one or more components, list a
  driver per runtime with an honest `status` (`untested` until someone has run it). Give it
  `pins`, `wiring`, `power`, `bench_test` and `troubleshooting`, and keep
  `datasheet_checked: false` until the values are confirmed against the datasheet.
- **Make a part buildable**: give its ESPHome driver a `template` (and `control` for an
  actuator); sensor entities are named `${id}_<quantity>`. Then check the output with
  `fsf firmware build ... --include-sim` and `esphome config`.
- **Add a board pin map**: `pins` in `catalog/boards/`. Mark strapping and shared pins with
  `caution`; they are accepted with a warning and never proposed.
- **Add a recipe**: new file in `catalog/recipes/`. Keep `verified: false` and `sources: []`
  until the values are checked against a growing reference. Quote times (`"06:00"`); never use
  `on:` as a YAML key (YAML reads it as `true`).
- **Add a scenario test**: use the `mock` fixture, drive time with `system.run(...)`, inject
  faults through `system.sim`, assert on `system.status()`, `system.led()`, `system.events()`.
- **Change control behaviour**: write the failing scenario test first; the suite is fast.

## Rules

- Never commit secrets, IP addresses of real devices, WiFi credentials, API keys or webhook
  ids. Local values go in `sites/local/secrets.yaml`; code reads them from environment
  variables or a gitignored file, and a `*.example.*` file documents the keys.
- Never commit databases, logs, photos or firmware binaries.
- No machine-specific absolute paths in code or docs.
- Python 3.12. Lint rules are in `pyproject.toml`.
