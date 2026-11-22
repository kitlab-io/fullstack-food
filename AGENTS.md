# AGENTS.md

Guide for coding agents and new contributors. Fullstack Food monitors and controls
small indoor growing setups (house plants, microgreens, mushrooms) on a local network.

## State of the repo

Mid-restructure. `docs/plan/restructure-plan.md` is the roadmap. Done so far: phase 0
(hygiene), phase 1 (schemas and catalog), phase 2 (hub, simulator, scenario tests) and
the status/LED engine from phase 3. Two follow-on plans have their first phase done:
`docs/plan/dashboard-plan.md` D1 (hub groundwork: decision trace, operator commands,
retention) and `docs/plan/installation-plan.md` I1 (assembly and test data per part, board
pin maps, pin validation). Nothing has run on real hardware yet, and no pin, wiring or
power value in the catalog has been confirmed on a bench (`datasheet_checked: false`).

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
| `packages/sim/fsf_sim` | Simulated nodes, zone physics, fault injection, `MockSystem` test harness |
| `tests/unit`, `tests/contract`, `tests/system` | Core logic, MQTT payload conformance, scenario tests |
| `deploy/` | Dockerfile and compose files for the mock stack |
| `iot-manager/`, `copilot/`, `nodes/`, `electronics/`, `homeassistant/` | Legacy prototype, kept for reference until later phases replace it. Do not extend it. |

## Commands

```
just validate          # catalog + example sites against the schemas
just validate --pins   # also propose board pins for devices that have none assigned
just test              # all tests, about a minute
just lint              # ruff, same as CI
just mock mushrooms 600   # simulated site against a real Mosquitto broker in Docker, 600x speed
just mock-watch        # tail every MQTT message of the running mock stack
```

Without `just`/`uv`: `pip install -e . pytest ruff`, then `python -m fsf_core validate`, `pytest`, `ruff check .`.

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
- Zone status comes from recipe target bands (debounced), alerts (immediate), and safety
  conditions (`offline`, `sensor_stale`, `reservoir_low`). The theme's `priority` list picks
  which one the LED segment shows.

## Common tasks

- **Add a part**: new file in `catalog/models/`, `implements` one or more components, list a
  driver per runtime with an honest `status` (`untested` until someone has run it). Give it
  `pins`, `wiring`, `power`, `bench_test` and `troubleshooting`, and keep
  `datasheet_checked: false` until the values are confirmed against the datasheet.
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
