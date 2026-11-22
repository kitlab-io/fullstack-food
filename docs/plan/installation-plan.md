# Installation, assembly, testing and troubleshooting plan

Status: proposal (2026-11-22). Nothing here is built. Today the system runs only against
simulated nodes; this plan is the path from that to a working physical installation that
someone else can replicate.

Hardware facts quoted below (pull-up values, voltage levels, sensor quirks) are from general
experience with these parts. Each must be confirmed against the part's datasheet and on the
bench before it goes into a published guide.

## 1. Principles

1. **One source of truth.** Wiring diagrams, BOMs, firmware configs, test procedures and
   troubleshooting pages are generated from the same `site.yaml` and catalog files the hub
   runs on. A guide cannot drift from the system it describes.
2. **Commission in stages.** A device is proven on the bench before it joins a node, a node
   before it joins a zone, a zone before a recipe is allowed to drive it.
3. **Nothing actuates until it has been tested.** New actuators start disabled; the hub
   observes and reports what it would do until the builder signs the zone off.
4. **Every failure the hub can detect has a page.** Each status (`sensor_stale`, `offline`,
   `reservoir_low`, ...) links to a symptom-first troubleshooting guide.

## 2. Installation paths

| Path | Audience | How |
|---|---|---|
| A. Mock | Anyone evaluating or developing | `pip install -e .` or the Docker mock stack. Exists today |
| B. Hub on Raspberry Pi OS (Bookworm, 64-bit) | First real target | Provisioning script + Docker Compose |
| C. Hub on Armbian (Orange Pi Zero 2W) | Second target | Same compose; board-specific notes |
| D. Home Assistant OS | HA Green/Yellow or a Pi on HAOS | Hub packaged as an add-on using the Mosquitto add-on |

### Hub install (paths B and C)

- `deploy/os/<target>/provision.sh`: installs Docker, creates the `fsf` user, enables I2C and
  1-Wire only if the site file has devices on the hub itself, sets hostname and mDNS name,
  sets the timezone from the site file.
- `fsf init`: creates `sites/local/` from an example, generates broker credentials per node,
  ESPHome API keys and OTA passwords into `sites/local/secrets.yaml`, and writes the
  Mosquitto password and ACL files.
- `docker compose -f deploy/compose/base.yaml -f deploy/compose/sbc.yaml up -d`.
- `fsf doctor`: preflight and health check (section 7). Must pass before nodes are added.
- Storage: database and photos on USB/NVMe or a NAS mount where available; documented
  SD-card-only mode with shorter retention.
- Updates: pinned image tags, `fsf update` pulls, validates the site against the new
  schemas, backs up the database, then restarts. Rollback is the previous tag.

### Node firmware

- `fsf firmware build <site>` generates one ESPHome YAML per node from the site file:
  board, WiFi and MQTT settings from secrets, one block per device from the model's ESPHome
  template, MQTT topics matching the contract, and the lease behaviour (on-commands carry
  `duration_s`; the node switches off on expiry; a boot-time default of everything off).
- First flash over USB (`fsf firmware flash <node>` wrapping the ESPHome CLI, or the browser
  flasher with release binaries for the reference designs); later updates over the air.
- CircuitPython remains a second runtime for boards ESPHome does not cover, with a small
  reference client implementing the same contract.
- A node contract test suite runs against any node, simulated or real: it checks state
  payloads against `schemas/mqtt/`, that an on-command expires, that `off` is honoured, and
  that the last-will `offline` appears when power is pulled.

## 3. Catalog additions this needs

The catalog currently says what a model implements and which drivers exist. Assembly and
testing need more per model, all validated by schema:

| Field | Purpose |
|---|---|
| `pins` | Signals the part needs (for example `sda`, `scl`, `adc`, `data`, `gate`) and electrical constraints (3.3 V only, needs ADC1, needs PWM) |
| `wiring` | Required support parts and notes: pull-ups, level shifter, flyback diode, series resistor, bulk capacitor, fuse |
| `power` | Supply voltage and peak current, so a power budget can be computed per node and rail |
| `drivers[].template` | The ESPHome (or other runtime) config snippet with placeholders for pins and ids |
| `calibration` | Procedure id and the values it produces (for example `dry`, `wet`) |
| `bench_test` | Expected plausible range at room conditions, settle time, and a stimulus check ("breathe on it: humidity must rise") |
| `troubleshooting` | Symptom, likely causes, checks, in order |
| `safety` | Mains voltage, water contact, heat: drives warnings in guides |

Boards gain a pin map (which pins are ADC-capable, strapping pins to avoid, I2C defaults),
so `fsf validate` can reject a site whose pin assignments cannot work, and suggest
assignments when pins are left blank.

## 4. Assembly

### Reference designs

One documented build per scenario, each a directory under `hardware/` with a KiCad project
or a perfboard layout, enclosure notes, and photos:

- **House plants**: one ESP32 node, soil probes, peristaltic pumps on MOSFET outputs,
  reservoir level sensor, air sensor, LED strip.
- **Microgreens**: as above plus a grow-light channel.
- **Mushrooms**: incubation node (air sensor, heat mat on a smart plug or relay) and fruiting
  node (CO2/temperature/humidity sensor, humidifier, fan, light, heater, LED strip).

### Generated per site

- **BOM** (CSV and XLSX): devices from the site file, plus the support parts each model's
  `wiring` requires, plus power supplies sized from the power budget.
- **Wiring diagram** (SVG) per node: board pins to devices, support parts, power rails.
- **Power budget**: per rail, with a warning when a strip or pump exceeds what the supply or
  the board's regulator can deliver.
- **Step-by-step build guide** (self-contained HTML): ordered so each step ends in a test.
- **LED legend card**: which segment is which zone and what each colour and effect means,
  printable.

### Safety rules written into every guide

- Mains loads (heat mats, humidifiers, some lights) are switched only through a certified
  smart plug or an enclosed, rated relay module. No exposed mains wiring.
- Low-voltage electronics sit above and away from water; drip loops on every cable; the
  reservoir sits lower than the electronics.
- Fuse on each 12 V rail; flyback protection on pumps and fans; common ground between
  supplies.
- LED strips: data-line level shifting from 3.3 V, a series resistor on data, a bulk
  capacitor at the strip, power injection for long strips.
- Heaters always paired with a temperature sensor in the same zone (the validator can
  enforce this) and a recipe `max_on` limit.
- Pumps get an anti-siphon arrangement so a stopped pump cannot drain the reservoir.

## 5. Testing and commissioning

Each step records its result in the hub store (who, when, measured values), and the
dashboard's devices page shows the commissioning state.

| Stage | Command | Passes when |
|---|---|---|
| 1. Bench, per device | `fsf bench <device>` | Sensor: reads continuously, value within the model's plausible range, responds to the stimulus check. Actuator: a 2-second leased pulse is confirmed by the builder |
| 2. Calibration | `fsf calibrate <device>` | Soil probe: dry and wet readings captured. Pump: volume delivered in a timed run measured, `flow_ml_per_s` written. Level sensor: empty and full captured. LED strip: each zone's segment lights in turn and is confirmed |
| 3. Node acceptance | `fsf node test <node>` | The node contract suite passes: payload schemas, lease expiry, off, last will, reconnect after WiFi loss |
| 4. Zone dry run | zone in `observe` mode | For 24 h the hub logs what it would do without actuating; the builder reviews the decision trace and the readings look sane |
| 5. Zone acceptance | `fsf zone test <zone>` | A shortened recipe exercises every loop for real: a small dose changes soil moisture, the heater raises temperature and stops at `max_on`, pulling the sensor triggers the fail-safe, an empty reservoir blocks the pump |
| 6. Soak | 48 h on the real recipe | No `sensor_stale`, `offline` or limit events that are not explained; watering volumes match the reservoir drop |

Hub features this requires:

- `observe` mode per zone (compute and log decisions, send no commands).
- Per-device commissioning state; a zone with an untested actuator stays in `observe`.
- `actuator_test` command (short lease, logged, shared with the dashboard plan).
- Shortened "acceptance" recipes derived from the real one by scaling durations.
- The hardware-in-the-loop test suite (`tests/hil/`): the existing scenario tests,
  parameterised to run against a real bench rig at real-time speed.

A board/OS/model combination that passes stages 1 to 5 is recorded in the catalog as
`verified` with `tested_on`, which feeds the published compatibility matrix.

## 6. Troubleshooting

### Structure

- **By status**: one page per hub status, generated. What it means, what the hub is doing
  about it (for example "heater held off"), likely causes in order, checks, and how to clear
  it. The LED legend, the dashboard banner and the event log all link here.
- **By symptom**: "pump runs but soil stays dry", "readings jump around", "node keeps
  rebooting", "strip shows wrong colours", "humidity never reaches target".
- **By part**: generated from each model's `troubleshooting` entries.
- Written twice from the same source: HTML for people, markdown under `docs/agents/` plus a
  `diagnose-zone` skill so a local LLM copilot can walk a user through the same checks using
  live data.

### New detections worth adding to the hub

| Detection | Signal |
|---|---|
| Dose had no effect | Soil moisture does not rise within a set time after a dose: airlock, kinked tube, probe out of the pot |
| Actuator not responding | Command sent, no ack, or state does not change |
| Heater or humidifier ineffective | On for a long time with no movement in the controlled quantity |
| Sensor stuck | Identical value for an implausibly long time |
| Sensor implausible | Outside the model's physical range, or a jump no real process could make |
| Reservoir drop does not match doses | Leak, siphoning, or wrong pump calibration |
| Node flapping | Repeated offline/online: WiFi signal or brown-out |

The simulator already has the matching fault injections for most of these (`pump_no_flow`,
`sensor_stuck`, `sensor_dropout`, `node_offline`), so each detection gets a scenario test
before it is tried on hardware.

### Known pitfalls to cover in the first guides

To be confirmed on the bench, then written up per part:

- Capacitive soil probes: per-probe calibration, exposed top edge needs sealing, readings
  drift with temperature and fertiliser.
- ESP32 analog inputs: on the original ESP32, ADC2 pins cannot be used while WiFi is on; use
  ADC1 pins. Strapping pins can stop the board booting if a sensor pulls them.
- DS18B20: needs a pull-up resistor on the data line; long cable runs need a lower value.
- DHT22: slow, needs a pull-up, minimum two seconds between reads.
- HC-SR04: 5 V echo signal needs a divider into a 3.3 V input; condensation and foam on the
  water give false readings.
- WS2812B / SK6812: 3.3 V data may be unreliable without level shifting; wrong colour order
  (RGB vs GRB vs GRBW) and wrong LED count are the usual "wrong colours" causes.
- Pumps and fans: brown-outs when a motor starts on a shared supply; missing flyback
  protection resets the node.
- SCD40 in a closed fruiting chamber: automatic self-calibration assumes regular fresh air,
  which a high-CO2 chamber does not provide; it should be disabled or the sensor recalibrated
  manually. Ultrasonic fog can also wet and skew humidity sensors placed in its path.
- Heat mats: slow and prone to overshoot; sensor placement relative to the mat matters.
- I2C: address clashes between identical sensors (needs a multiplexer), bus length, missing
  pull-ups on bare sensor boards.
- WiFi: 2.4 GHz only on most ESP32 boards; signal inside a grow tent or metal rack.

### `fsf doctor`

Runs on the hub and prints a pass/fail list with the fix for each failure: Docker and
compose versions, broker reachable and credentials valid, site validates, each node's last
seen and firmware version, each sensor's last reading age and plausibility, clock sync, disk
space and database size, backup age. `--bundle` writes a diagnostics archive with secrets
redacted, suitable for attaching to an issue.

## 7. Documentation outputs

All generated by the doc pipeline in the main plan (phase 4) from the sources above:

| Output | For |
|---|---|
| Install guide per OS target (HTML) | People setting up a hub |
| Build guide per reference design and per site (HTML + SVG wiring + BOM XLSX) | Builders |
| Commissioning checklist per site (HTML, printable) | Builders |
| Troubleshooting pages by status, symptom and part (HTML) | Users |
| `docs/agents/install.md`, `commission.md`, `troubleshoot.md` and skills `commission-node`, `diagnose-zone`, `flash-node` | LLM agents and the local copilot |
| Compatibility matrix (HTML and markdown) | Everyone choosing parts |

## 8. Phases

| Phase | Scope | Done when |
|---|---|---|
| I1. Catalog depth | Schema fields in section 3; fill them for every model used by the three example sites; board pin maps; pin validation | `fsf validate` rejects an impossible pin assignment and proposes a valid one |
| I2. Firmware generation | ESPHome generation, flash wrapper, node contract suite, lease behaviour on a real ESP32 | One real node passes the contract suite that the simulated node passes |
| I3. Bench rig and commissioning tools | `fsf bench`, `fsf calibrate`, `observe` mode, commissioning state, acceptance recipes, `tests/hil/` | The house plant reference build passes stages 1 to 5 on Raspberry Pi OS |
| I4. Generated build docs | BOM, wiring SVG, power budget, build guide, checklist, legend card | A second person builds the house plant design from the guide alone |
| I5. Troubleshooting | New hub detections with scenario tests, status/symptom/part pages, `fsf doctor`, agent skill | Each injected fault leads to the right page and the documented fix clears it |
| I6. Remaining scenarios and targets | Microgreens and mushroom builds; Armbian; HAOS add-on | All three reference builds are `verified` on at least one target |

I1 and the dashboard plan's D1 are independent and can run in parallel. I3 benefits from the
dashboard's devices page but does not depend on it; everything works from the command line.

## 9. Decisions needed

1. **First real hardware target.** Recommended: Raspberry Pi OS on a Pi with one ESP32 node,
   house plant build, because it has the fewest parts and no mains loads.
2. **Mains switching.** Recommended: certified smart plugs only in the published guides, no
   DIY relay boards for mains. The Kasa strip already in the repo fits; it needs a driver
   and a lease equivalent (the hub must turn it off, since the plug cannot expire a command
   itself; that weakens the fail-safe and should be stated in the guide).
3. **Sensors on the hub itself.** The prototype wired sensors directly to the Pi. Supporting
   that needs a local Linux node runtime speaking the same contract. Recommended: defer;
   start with ESP32 nodes only.
4. **Reference PCB or perfboard.** A PCB makes builds repeatable but slows iteration.
   Recommended: perfboard and breakout modules for the first verified builds, PCB after.
