# Fullstack Food: repo restructure, mock system test, and doc generation plan

Status: proposal (2026-11-22). Nothing in this plan has been implemented yet.

## 1. Where the repo is today

About 1,300 lines of prototype Python plus configs, KiCad files and notes.

| Area | Current state | Problem for the goals |
|---|---|---|
| `iot-manager/` | Redis + RQ worker/scheduler, SQLite datastore, device classes, Flask/Vue tutorial scaffold | Device classes are stubs (`super.__init__` bug means actuators cannot even be constructed), jobs are hardcoded to `light_cwww[0]`, paths are hardcoded to one Mac |
| `iot-manager/config/*.yaml`, `copilot/config/gardenplan.yaml` | Two overlapping config formats for devices, zones and protocols | No schema, no validation, generic type and exact model are mixed in one record, typos (`soil_mositure`, `acuators`, `ds1bb20`) silently pass |
| `iot-manager/tests/` | Three stub tests, one synthetic temperature generator | No system test; nothing runs without hardware |
| `nodes/`, `electronics/`, `homeassistant/` | One CircuitPython demo, one KiCad project, HA config in a misspelled `.homeassisant` dir | No link between a hardware design, its firmware and its config |
| `docs/` | Two drawio SVGs, a 25-line architecture outline, two links | No generated docs, nothing aimed at agents |
| Repo hygiene | Committed: WiFi SSID and password (`nodes/mcu/firmware/circuitpython/boot.py`), ESPHome API encryption keys (`iot-manager/services/esphome_api_test.py`), an HA webhook URL (`README.md`), `sensordata.db`, `dump.rdb`, a firmware `.bin`, photos, personal `.bashrc`/`.zshenv` | Secrets are in git history; binaries bloat the repo |

## 2. Architecture decisions

These shape everything else. Each is a recommendation, with the main alternative noted.

1. **MQTT is the contract between nodes and the hub.** Every sensor reading and actuator command crosses a Mosquitto broker using one topic and payload schema. A simulated node and a real ESP32 are indistinguishable to the hub, so the mock system test exercises the real control code. Alternative: direct driver calls inside the hub process (what exists now), which makes mock and real paths diverge.
2. **Replace Redis + RQ with one asyncio hub service** with an in-process scheduler and an injectable clock. Fewer services on a 1 GB SBC, and an injectable clock lets tests run a 30-day grow in seconds. Alternative: keep RQ; it works but needs Redis, a worker and a scheduler process, and cannot be time-accelerated.
3. **ESPHome is the default MCU firmware**, with node YAML generated from the site config. It gives OTA, API encryption and native Home Assistant support for free. CircuitPython stays as a second supported runtime for boards or sensors ESPHome does not cover.
4. **Home Assistant is optional, not required.** The hub publishes HA MQTT discovery messages, so HA picks everything up when present, but the stack also runs on a bare Raspberry Pi OS or Armbian box. On HAOS the hub ships as an add-on.
5. **Three-layer definitions: component, model, site.** Generic capability, exact part, and a specific installation are separate files validated by JSON Schema (section 4).
6. **SQLite (WAL mode) for readings and events** at this scale, behind a small storage interface so a time-series database can replace it later.

## 3. Target repo structure

```
fullstack-food/
├─ README.md                 # human entry point: what it is, 5-minute mock quickstart
├─ AGENTS.md                 # agent entry point: layout, commands, conventions
├─ justfile                  # one-word tasks: mock, test, docs, flash, deploy
├─ pyproject.toml            # uv workspace, pinned lockfile
│
├─ schemas/                  # JSON Schema: single source of truth for all YAML
│  ├─ component.schema.json  ├─ model.schema.json   ├─ board.schema.json
│  ├─ site.schema.json       ├─ species.schema.json ├─ recipe.schema.json
│  └─ mqtt/                  # payload schemas for state, command, status
│
├─ catalog/                  # reusable, shared across all users
│  ├─ components/            # generic: sensor.soil_moisture, actuator.pump ...
│  ├─ models/                # exact parts: bosch.bme280, worldsemi.sk6812-rgbw ...
│  ├─ boards/                # SBCs and MCUs: rpi-zero-2w, opi-zero-2w, esp32-c3 ...
│  ├─ species/               # pothos, radish-microgreens, blue-oyster ...
│  ├─ recipes/               # climate recipes per species
│  └─ themes/                # LED status colour themes
│
├─ sites/
│  ├─ examples/              # houseplants/, microgreens/, mushrooms/ (used by tests)
│  └─ local/                 # a user's real site; gitignored
│
├─ packages/
│  ├─ core/                  # schema models, loaders, units, recipe resolution
│  ├─ hub/                   # controller, scheduler, safety, storage, API
│  ├─ drivers/               # mqtt, linux i2c/gpio/1-wire, kasa, usb camera
│  ├─ sim/                   # simulated nodes + zone physics + fault injection
│  ├─ web/                   # Vue dashboard (replaces flask-vue-crud scaffold)
│  ├─ copilot/               # local-LLM agent, MCP server, vision
│  └─ docgen/                # all generators (section 8)
│
├─ firmware/
│  ├─ esphome/               # shared packages + generated per-node YAML
│  ├─ circuitpython/         # alternative runtime
│  └─ toolchain/             # pinned build container, flash scripts, manifests
│
├─ hardware/
│  └─ <design>/              # KiCad project, bom.csv, enclosure, README per design
│
├─ deploy/
│  ├─ compose/               # base.yaml + mock.yaml + sbc.yaml overlays
│  ├─ os/                    # raspberry-pi-os/, armbian/, haos-addon/
│  ├─ security/              # mosquitto ACL templates, firewall, secrets template
│  └─ backup/                # restic config, restore script
│
├─ docs/
│  ├─ guides/                # handwritten markdown (source)
│  ├─ agents/                # markdown written for LLMs (partly generated)
│  ├─ diagrams/              # diagram sources
│  └─ plan/                  # this file
│
├─ .claude/skills/           # agent skills (section 8)
└─ tests/
   ├─ unit/  ├─ contract/    # schema + MQTT payload conformance
   ├─ system/                # scenario tests against the mock stack
   └─ hil/                   # same scenarios against a bench rig
```

Generated output (`build/docs/`, firmware binaries, exported schematics) is not committed. CI builds it and attaches it to GitHub Releases and Pages.

Migration map:

| From | To |
|---|---|
| `iot-manager/services`, `datastore.py`, `protocols.py` | `packages/hub` |
| `iot-manager/devices/__init__.py`, `devices/tests/*.py` | `packages/drivers` (the bench scripts become driver smoke tests) |
| `iot-manager/tests/mock/sensors.py` | `packages/sim` |
| `iot-manager/flask-vue-crud` | `packages/web` (keep `SensorData.vue` and `LineChart.vue`, drop the Books tutorial) |
| `iot-manager/config/devices.yaml` | split into `catalog/models/*` and `sites/examples/*` |
| `protocols.yaml`, `gardenplan.yaml` | `catalog/recipes/*` and `sites/examples/*` |
| `copilot/` | `packages/copilot` |
| `nodes/mcu/firmware` | `firmware/` (the `.bin` moves to a release asset) |
| `nodes/singleboardcomputer`, `homeassistant/` | `deploy/os/*` |
| `electronics/` | `hardware/copilot-server/` |
| `developer/`, `.bashrc`, `codemcp.toml` | removed; replaced by `AGENTS.md` and `.claude/` |

## 4. Definition schemas

### 4.1 Component (generic capability)

```yaml
kind: Component
id: sensor.air_temp_humidity
class: sensor                     # sensor | actuator | indicator | camera
measures:
  - { quantity: air_temperature,   unit: degC }
  - { quantity: relative_humidity, unit: percent }
```

```yaml
kind: Component
id: actuator.pump
class: actuator
commands:
  - { name: run, args: { duration_s: number } }   # always time-bounded
  - { name: stop }
safety: { requires_max_on: true }                  # hub refuses to drive it without a limit
```

Initial component set: `sensor.air_temp_humidity`, `sensor.soil_moisture`, `sensor.soil_temperature`, `sensor.light`, `sensor.co2`, `sensor.water_level`, `sensor.barometric_pressure`, `camera.still`, `actuator.pump`, `actuator.valve`, `actuator.grow_light`, `actuator.heater`, `actuator.humidifier`, `actuator.fan`, `actuator.relay`, `indicator.led_strip`.

### 4.2 Model (exact part, drivers, compatibility)

```yaml
kind: Model
id: bosch.bme280
implements: [sensor.air_temp_humidity, sensor.barometric_pressure]
interface: { bus: i2c, addresses: [0x76, 0x77], supply_v: [1.8, 3.6] }
specs:
  air_temperature:   { range: [-40, 85], accuracy: 1.0 }
  relative_humidity: { range: [0, 100],  accuracy: 3.0 }
drivers:
  - runtime: esphome
    platform: bme280_i2c
    versions: ">=2024.6"
    status: verified               # verified | community | untested
  - runtime: linux
    module: adafruit_bme280
    tested_on: [raspberry-pi-os-bookworm/rpi-zero-2w, armbian-bookworm/opi-zero-2w]
    status: verified
  - runtime: sim
    profile: air_th
bom: { mpn: BME280, typical_module: "GY-BME280 3.3V breakout" }
notes: "Self-heats about 1 degC in a sealed enclosure."
```

`drivers[].status` and `tested_on` feed a generated compatibility matrix (model x runtime x board/OS). Boards use the same pattern (`catalog/boards/`), listing buses, pins, supported OS images and firmware targets.

### 4.3 Site (one installation)

```yaml
kind: Site
id: home
hub: { board: rpi-zero-2w, os: raspberry-pi-os-bookworm }
nodes:
  - id: shelf-node
    board: esp32-c3-devkitm
    runtime: esphome
    devices:
      - { id: tray1-soil,  model: generic.capacitive-soil-v1.2, as: sensor.soil_moisture,
          pins: { adc: GPIO3 }, calibration: { dry: 2800, wet: 1200 } }
      - { id: tray1-pump,  model: generic.12v-peristaltic,       as: actuator.pump,
          pins: { gate: GPIO5 }, flow_ml_per_s: 1.6 }
      - { id: shelf-strip, model: worldsemi.sk6812-rgbw,         as: indicator.led_strip,
          pins: { data: GPIO8 }, led_count: 30 }
zones:
  - id: tray1
    kind: microgreens_tray        # houseplant | microgreens_tray | chamber
    devices: [tray1-soil, tray1-pump]
    planting: { species: radish-microgreens, recipe: radish-microgreens.standard,
                started_at: 2026-11-20, goal: balanced }
    indicator: { strip: shelf-strip, leds: [0, 9] }
```

A device binds a model to a generic role with `as:`. The hub and recipes only ever refer to roles within a zone, so swapping a BME280 for an SHT31 changes one line.

### 4.4 MQTT contract

```
fsf/<site>/<node>/<device>/state     retained   {"t": "...", "air_temperature": 21.4, ...}
fsf/<site>/<node>/<device>/cmd                  {"id": "...", "name": "run", "duration_s": 20}
fsf/<site>/<node>/<device>/ack                  {"id": "...", "ok": true}
fsf/<site>/<node>/status             LWT        online | offline
fsf/<site>/zone/<zone>/status        retained   {"state": "needs_water", "stage": "blackout", ...}
```

## 5. Climate control schemas

### 5.1 Layering

The effective setpoints for a zone are resolved in this order, later layers overriding earlier ones:

`species defaults -> recipe stage -> goal overlay -> zone override`

The resolved result is written to the event log, so any setpoint can be traced to the layer that produced it.

### 5.2 Steady-state recipe (house plants)

```yaml
kind: Recipe
id: pothos.steady
species: pothos
mode: steady
targets:
  soil_moisture:   { min: 30, max: 60, unit: percent, strategy: dry_down }
  air_temperature: { min: 16, max: 29, unit: degC,    control: monitor_only }
  light:           { min_dli: 4,                      control: monitor_only }
control:
  watering:
    trigger: { quantity: soil_moisture, below: 30, for: 2h }
    dose:    { volume_ml: 150 }
    limits:  { min_interval: 48h, max_daily_ml: 300 }
alerts:
  - { when: "air_temperature < 12", severity: critical, status: too_cold }
  - { when: "soil_moisture < 20",   severity: warn,     status: needs_water }
```

### 5.3 Staged recipe (microgreens, mushrooms)

```yaml
kind: Recipe
id: blue-oyster.standard
species: blue-oyster
mode: staged
stages:
  - id: incubation
    zone_role: incubation                 # which chamber zone this stage needs
    duration: { typical: 14d, min: 10d, max: 21d }
    advance:  { on: manual, hint: "substrate fully colonised" }
    targets:
      air_temperature:   { min: 21, target: 24, max: 27, unit: degC }
      relative_humidity: { min: 60, max: 75, unit: percent }
      light:             { photoperiod: 0h }
  - id: fruiting
    zone_role: fruiting
    duration: { typical: 7d, min: 5d, max: 12d }
    advance:  { on: manual, hint: "caps flatten" }
    targets:
      air_temperature:   { min: 13, target: 16, max: 18, unit: degC }
      relative_humidity: { min: 85, target: 90, max: 95, unit: percent }
      co2:               { max: 1000, unit: ppm }
      light:             { photoperiod: 12h, intensity: low }
    control:
      fresh_air: { strategy: duty_cycle, on: 2m, every: 20m, also_when: "co2 > 1000" }
      humidity:  { strategy: hysteresis, band: 3, limits: { max_on: 10m, min_off: 2m } }
  - id: harvest
    advance: { on: manual }
    notify: true
```

Microgreens use the same shape with stages `germination -> blackout -> light -> harvest`, where `advance.on` is usually `elapsed`.

All numeric values in the example recipes are placeholders to illustrate the schema. Each shipped recipe needs its values checked against a cited growing reference, recorded in a `sources:` field.

Schema features:

- **Targets**: `{min, target, max}` per quantity, with optional `day:` and `night:` variants.
- **Advance conditions**: `manual`, `elapsed`, or `condition` (an expression over sensor quantities). Stage changes are events and can be undone.
- **Zone roles**: a mushroom grow moves between an incubation zone and a fruiting zone. The planting tracks which zone it is in; each chamber zone runs the stage of the planting it currently holds.
- **Control strategies**: `hysteresis`, `duty_cycle`, `schedule`, `dose` (for watering), `monitor_only`.
- **Goal overlays** (`catalog/recipes/goals/`): `balanced`, `max_yield`, `energy_saver`, `quiet` (fan limits, night hours), `vacation` (wider bands, conservative watering). An overlay is a partial recipe merged on top.
- **Safety limits** are separate from targets and enforced by the hub regardless of recipe: maximum on-time, minimum off-time, daily volume caps, interlocks (no pump if reservoir is low; heater off if its temperature sensor is stale or the node is offline). Node firmware also enforces a maximum on-time locally so a hub crash cannot leave a pump or heater running.

## 6. Feedback LED strips

A strip is an `indicator.led_strip` device. Zones claim segments of it (`indicator: { strip, leds: [0, 9] }`). The hub computes one status per zone, picks the highest-priority one, and publishes a render command for the segment.

```yaml
kind: Theme
id: default
brightness: { day: 0.5, night: 0.05, night_hours: [22, 7] }
priority: [offline, critical, too_hot, too_cold, needs_water, too_dry, too_humid,
           reservoir_low, stage_ready, ok]
statuses:
  ok:            { color: [0, 60, 0, 0],    effect: solid }
  needs_water:   { color: [0, 0, 255, 0],   effect: breathe }
  too_cold:      { color: [0, 180, 255, 0], effect: solid }
  too_hot:       { color: [255, 40, 0, 0],  effect: solid }
  too_dry:       { color: [255, 160, 0, 0], effect: solid }
  too_humid:     { color: [120, 0, 255, 0], effect: solid }
  reservoir_low: { color: [0, 0, 255, 0],   effect: blink }
  stage_ready:   { color: [0, 0, 0, 255],   effect: breathe }   # W channel
  offline:       { color: [255, 0, 255, 0], effect: blink_slow }
```

- Colours are RGBW. For RGB-only models (WS2812B) the generator maps W to equal RGB; the model definition declares `channels: rgb | rgbw` and colour order.
- Each status has an effect as well as a colour, so states remain distinguishable for colour-blind users.
- Rendering runs on the node (ESPHome addressable light effects), so the strip keeps showing the last status if the hub restarts, and shows `offline` if the node loses the hub.
- The simulator records LED commands, so tests can assert "segment for tray1 shows `too_cold`".

## 7. Mock system test, then real hardware

### 7.1 Mock stack (any Linux, no hardware)

`just mock` runs `deploy/compose/base.yaml + mock.yaml`: Mosquitto, hub, web and `sim`.

`packages/sim` contains:

- **Simulated nodes**: one per node in the site file, speaking the exact MQTT contract, including acks, LWT and local max-on-time.
- **Zone physics**: small first-order models. Soil moisture decays with evaporation and rises with pump volume; chamber temperature and humidity respond to heater, humidifier, fan and ambient conditions; CO2 rises with colonised substrate and falls with fresh air; reservoir level drops with pumping.
- **Synthetic drivers**: ambient day/night profiles, seeded noise, calibration drift.
- **Fault injection**: sensor dropout, stuck-at values, node offline, pump runs but moisture does not rise, empty reservoir, broker restart.
- **Accelerated clock**: hub and sim share an injectable clock.

Scenario tests in `tests/system/` (pytest, run in CI on x86-64 and arm64):

| Scenario | Assertions |
|---|---|
| House plants | Dry pot is watered within limits; daily cap is never exceeded; LED goes `needs_water` then `ok`; empty reservoir blocks the pump and raises `reservoir_low` |
| Microgreens | Stages advance on schedule; light is off in blackout and follows the photoperiod afterwards; cold ambient produces `too_cold` on the strip |
| Mushrooms | Incubation zone holds its temperature band; moving to fruiting switches setpoints; humidity and CO2 stay in band; heater shuts off when its sensor goes stale |
| Resilience | Hub restart resumes the correct stage; node offline produces `offline` status and no stuck actuator |

### 7.2 Transition to hardware

1. **Bench rig (HIL)**: one ESP32 node with a real sensor, relay and LED strip, driven by the same scenario tests in `tests/hil/` at real-time speed with shortened recipes.
2. **Mixed mode**: a site file may mark individual nodes `runtime: sim`, so a real hub can run with some real and some simulated nodes.
3. **OS targets**, in order:
   - Raspberry Pi OS (Bookworm, 64-bit): Docker Compose, provisioning script in `deploy/os/raspberry-pi-os/`.
   - Armbian on Orange Pi Zero 2W: same compose, board-specific notes for I2C/1-Wire overlays.
   - Home Assistant OS (HA Green/Yellow or a Pi running HAOS): HAOS does not run arbitrary compose stacks, so the hub is packaged as an add-on that uses the Mosquitto add-on.
4. Each board/OS pair that passes the HIL suite is recorded in the catalog and appears in the generated compatibility matrix.

## 8. Documentation generation

Sources of truth are `schemas/`, `catalog/`, `sites/`, `hardware/` and handwritten `docs/guides/`. Everything else is generated by `just docs`.

| Audience | Output | Generated from |
|---|---|---|
| LLMs and agents | `AGENTS.md`, `docs/agents/*.md` (schema reference, MQTT contract, catalog index, per-site summary), `llms.txt` | schemas, catalog, sites |
| LLMs and agents | `.claude/skills/`: `add-model`, `new-site`, `write-recipe`, `diagnose-zone`, `flash-node` | handwritten, each referencing generated references |
| Humans | One self-contained HTML file per guide (inline CSS and SVG, works offline from a NAS share): quickstart, one build guide per scenario, operations, troubleshooting | `docs/guides/*.md` + templates |
| Humans | SVG: system topology and zone map per site; per-node wiring diagram; recipe timeline chart; LED legend card | site file, catalog, recipe |
| Builders | Schematic SVG/PDF, PCB renders, gerbers, interactive HTML BOM | `kicad-cli` on `hardware/*` |
| Builders | Per-site BOM as CSV and XLSX (quantities, models, suggested parts) | site file x catalog `bom` fields |
| Builders | Per-node ESPHome YAML; compiled binaries with SHA-256 and a browser-flash manifest | site file, pinned toolchain container |
| Replicators | Compose bundles, HAOS add-on, provisioning scripts, compatibility matrix | `deploy/`, catalog |

CI runs schema validation, the scenario tests and `just docs`; a tagged release publishes the HTML set, firmware binaries, BOMs and KiCad exports as release assets.

## 9. Local network, security, backups, integrations

**Security**
- Rotate the WiFi password, ESPHome keys and HA webhook that are in git history, then decide whether to rewrite history (section 11).
- No secrets in the repo: `sites/local/secrets.yaml` is gitignored, with an optional sops + age encrypted variant for sharing between collaborators. A pre-commit secret scanner enforces this.
- Mosquitto: no anonymous access, one credential per node, ACLs restricting each node to its own topic subtree, TLS on the LAN listener.
- ESPHome: API encryption key and OTA password generated per node.
- Web UI and API behind a reverse proxy with authentication; nothing is exposed to the internet; remote access only through the user's own VPN.
- Guide for placing nodes on an IoT VLAN or guest SSID that can reach only the broker.
- Containers run as non-root with only the device access they need (I2C, GPIO, camera).

**Backups**
- Nightly restic job: consistent SQLite snapshot, site config, recipes, photos. Targets: NAS over SMB/NFS/SFTP or an S3-compatible bucket on the NAS. Encrypted, with retention rules.
- `just restore` rebuilds a hub from a fresh OS image plus the backup; a CI test restores a backup into the mock stack to prove it works.
- SD card wear: database and photos on USB/NVMe or the NAS where available.

**Local LLMs**
- `packages/copilot` talks to any OpenAI-compatible local endpoint (Ollama, llama.cpp), configured per site; no cloud dependency.
- An MCP server exposes read tools (zone status, history, recipe, photos) and write tools (advance stage, water now, adjust override). Write tools pass through the same safety limits as recipes and can require confirmation in the UI.
- Vision: periodic photo analysis with a local vision model, stored as events.
- The generated `docs/agents/` set is the copilot's reference context.

**NAS and media servers**
- Photos and generated timelapse videos are written to a NAS share in a `site/zone/date` layout that Immich, Jellyfin or Plex can index directly.
- The self-contained HTML docs can be served from the same share.

## 10. Phases

| Phase | Scope | Done when |
|---|---|---|
| 0. Hygiene | Remove secrets, databases, binaries and personal dotfiles from the tree; fix `.gitignore`; add `AGENTS.md`, `pyproject.toml`, `justfile`, CI skeleton | Clean tree, CI green on lint |
| 1. Schemas and catalog | JSON Schemas; components; models for every part already used in the repo; three example sites; draft recipes; validator CLI | `just validate` passes on all examples |
| 2. Hub and mock test | Move code into `packages/`; MQTT contract; asyncio hub with safety layer; `sim`; scenario tests for all three scenarios | `just mock` runs on a clean Linux machine; scenario suite green in CI |
| 3. LED feedback | Status engine, theme schema, ESPHome effects, sim recording | LED assertions pass in scenario tests |
| 4. Doc generation | `docgen` for agent markdown, HTML, SVG, BOM, KiCad exports; skills | `just docs` output published by CI |
| 5. Hardware bring-up | ESPHome generation, bench rig, HIL suite; Raspberry Pi OS, then Armbian, then HAOS add-on | House plant scenario passes on real hardware on each target |
| 6. Security and backups | Broker ACLs/TLS, secrets flow, restic, restore test | Restore test green; security checklist in docs |
| 7. Integrations | Local LLM copilot + MCP server, photo/timelapse to NAS, HA discovery polish | Copilot answers status questions and performs a guarded action in the mock stack |

Phases 3 and 4 can run in parallel after phase 2. Phase 6 basics (no anonymous broker, no secrets in repo) land in phases 0 and 2; the rest hardens before real deployments.

## 11. Decisions needed

1. **Git history**: the leaked WiFi password and ESPHome keys remain in history after phase 0. Rotating them is required either way. Rewriting history removes them but forces every collaborator to re-clone. Recommended: rotate, and rewrite only if the repo is or will be public.
2. **Redis/RQ removal** (decision 2 above).
3. **ESPHome as default firmware** (decision 3).
4. **Home Assistant optional** (decision 4), which commits to maintaining a HAOS add-on.
5. **Licence for catalog and recipes**: whether community-contributed species and model files follow the repo licence.
