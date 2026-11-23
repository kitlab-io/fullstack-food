# Studio plan: designing, simulating and managing sites

Status (2026-11-23): the recommended options in section 12 are accepted. Phase S1 is built;
S2 to S6 are not started. It builds on the hub, simulator, dashboard and tools described in
`AGENTS.md`, and it reverses one non-goal of the dashboard plan: editing site and recipe
files in the browser.

How S1 stands:

- **Safety envelope.** A species has `limits` per quantity; a recipe, goal or planting
  override whose band leaves them does not validate, and the hub refuses such an override.
  A site has `safety.actuator_limits` per actuator kind (`max_on`, `max_daily_ml`) that no
  recipe may exceed. The four example species have limits; like the recipes they are
  placeholders that bracket the examples, not horticultural advice.
- **Layered library.** A site folder may have `library/` with its own species, recipes,
  goals and themes. They are added to the built-in catalog for that site; they cannot
  replace a built-in entry, and parts and boards are refused there.
- **Round-trip writing** (`fsf_core/yamlio.py`, ruamel.yaml). Every catalog and example
  file keeps its data, comments and order, and a second save changes nothing. The first
  save does tidy spacing inside `{ ... }` and drops column alignment; it is not
  byte-identical.
- **Revision store** (`packages/studio/fsf_studio`). Numbered snapshots of `site.yaml` and
  `library/` with who, when, a message and the parent; saved only if they validate; a
  stale draft is refused; diff and restore. Secrets are never included. Which revision is
  applied is recorded, but nothing applies one to a hub yet (S4).
- **Roles.** Viewer, operator and admin, one shared password each
  (`FSF_WEB_VIEWER_PASSWORD_HASH`, `FSF_WEB_PASSWORD_HASH`, `FSF_WEB_ADMIN_PASSWORD_HASH`).
  `/api/studio/*` needs the admin; the only endpoint there so far lists revisions. The
  mock stack's no-login mode counts as admin.
- Not in S1: limits are not yet editable anywhere but the files, there is no editor, and
  the dashboard does not show the envelope next to a band.

Statements about Tauri and Electron below are from general knowledge of both, not from a
trial. Build a throwaway shell with each before committing (decision 1).

## 1. What this is for

Today a site, a recipe or a test scenario is made by editing YAML by hand and, for
scenarios, writing Python. The studio makes those things editable by someone who does not
read YAML, and makes changing a live site safe.

Three jobs, in order of risk:

1. **Design**: create and edit sites (nodes, devices, zones, plantings) and the library
   they draw on (species, recipes, goals, parts, boards, themes).
2. **Simulate**: define a scenario (a site, a simulated environment, things that happen
   over time, what must be true) and run it, before anything real is touched.
3. **Manage a live site**: change the running configuration of a hub with a clear view of
   what will change, a way back, and no way around the hub's safety rules.

It comes in two shapes that share one codebase:

| Shape | Runs on | For |
|---|---|---|
| **Hub studio** (web) | The hub SBC, next to the dashboard | Managing the live site from any device on the network: edit, check, apply, roll back |
| **Desktop studio** | A laptop | Designing offline, running the full simulator, building and flashing firmware, pushing changes to one or more hubs |

Non-goals: cloud accounts or sync, multi-user editing at the same time, a visual
circuit-board editor, editing the control code of the hub itself.

## 2. Words used here

The request says "controllers". This plan reads that as two things the system already has,
and covers both: **nodes** (the microcontroller or power strip a device is attached to) and
**control loops** (the rules inside a recipe stage that drive an actuator). If something
else was meant, say so (decision 7).

- **Library**: species, recipes, goals, components, models (parts), boards, themes,
  troubleshooting. Today this is `catalog/`.
- **Site**: one installation: `site.yaml`, plus its secrets, which the studio never shows.
- **Scenario**: a site, a simulated environment (today `sim.yaml`), a timeline of events,
  and expectations. Today scenarios exist only as Python tests in `tests/system/`.
- **Revision**: one saved, validated state of a site and its own library entries.
- **Draft**: a revision being edited. It is not running anywhere.

## 3. Architecture

```
                 one frontend (Vue, the existing dashboard plus Studio pages)
                                   |
                         one HTTP API (fsf_studio)
              drafts, validation, diff, revisions, scenarios, library
                 /                                        \
   HUB STUDIO (on the SBC)                      DESKTOP STUDIO (on a laptop)
   served by the dashboard service               a shell around the same API,
   apply = hand a revision to the hub            started as a local process
   short what-if runs only                       + simulator and hub in-process
                                                 + firmware build and flash
                                                 + "remotes": hubs it can pull from and push to
```

- **One API, two hosts.** A new package `packages/studio/fsf_studio` holds everything that
  is not presentation: reading and writing files, validation, diff, revisions, the scenario
  runner. The dashboard service mounts it under `/api/studio` on the hub. The desktop app
  starts the same service on `127.0.0.1` with more features switched on.
- **One frontend.** The existing Vue app gains a Studio section. On the hub it appears for
  people with the admin role; in the desktop app it is the main thing, and the dashboard
  pages show the result of a simulation run exactly as they show a live site.
- **Files stay the source of truth.** The studio edits the same YAML the hub loads, checked
  by the same schemas and the same `load_site`. There is no second model in a database to
  drift from the files.
- **Applying is the hub's job.** The studio proposes a revision; the hub validates it again
  and switches to it. Neither the web app nor the desktop app writes into the hub's running
  configuration directly. This is the same rule the dashboard follows for actions.

### What the code needs that it does not have

| Need | Today | Change |
|---|---|---|
| A library a user can add to | One `catalog/` in the repository | Layered library: built-in catalog, then a per-site overlay (`sites/local/<site>/library/`). `Catalog.load` takes several roots; a later root may add entries and may override only what the site created |
| Writing YAML back | Files are only read | Round-trip writing that keeps comments and order (ruamel.yaml), or a canonical writer; see decision 4 |
| Revisions | None | A revision store per site: files plus a manifest (parent, who, when, message, validation and simulation results) |
| Switching configuration | The hub loads the site once, at start | Apply by controlled restart first (section 6), in-place reload later if needed |
| Scenarios as data | Python tests | A `Scenario` kind with a schema, and a runner |
| Roles | One shared login | Viewer, operator, admin (section 8) |
| Limits a recipe cannot exceed | Species have defaults and alerts, no hard limits | A safety envelope (section 7) |

## 4. Design: the editors

All editors work on a draft, validate as you type with the real validators, and show
problems next to the field that causes them.

| Editor | Edits | Shows while editing |
|---|---|---|
| **Site** | Nodes and their board and runtime, devices (pick a part from the library), zones and their devices, LED segments, plantings | Pin assignment with the existing checks and proposals; the generated wiring diagram, BOM and power budget, live |
| **Recipe** | Stages on a timeline, target bands, control loops (dose, hysteresis, duty cycle, schedule), limits, alerts, how a stage advances | The bands against the species' safety envelope; which actuators a site must have for it; a quick simulation of the stage |
| **Species, goals** | Defaults, envelope, goal overlays | Which recipes and plantings use them |
| **Theme** | Status colours, effects, priority, labels | A strip preview with the same effects as the dashboard |
| **Parts and boards** | What a part implements, its signals, wiring, power, bench test, troubleshooting, driver templates; a board's pin map | Which sites use it; the "not yet confirmed on hardware" flag |
| **Scenario** | Section 5 | Section 5 |
| **Raw** | Any file as YAML, with schema checking | The escape hatch for whatever a form does not cover yet |

Forms for the five kinds people edit most (site, recipe, species, goal, theme) are built by
hand, because their value is in the custom parts: a timeline, a band slider, a pin picker.
Everything else gets a generic form generated from its JSON Schema, plus the raw editor.

Built in from the start, because they are what makes this safer than a text editor:

- **Impact preview.** Before saving, a plain-language list of what the change does: "adds
  a pump to zone tray1, which will stay in observe mode until it passes a bench test",
  "node shelf-node needs new firmware", "raises the humidity target of the fruiting stage
  from 90 to 93".
- **No dangling references.** Renaming or deleting something that is used offers to
  update or lists the users; it never leaves a broken file.
- **Starting points.** New site from an example; new recipe from an existing one.

## 5. Simulate: scenarios as data

A scenario file replaces what a Python scenario test says today:

```yaml
kind: Scenario
id: heater-fails-overnight
site: mushrooms                 # a site id, or a revision of one
environment:                    # what sim.yaml holds today
  ambient: { air_temperature: { mean: 14, daily_amplitude: 1.5 }, relative_humidity: 50 }
  zones: { incubation-chamber: { enclosure: chamber, air: { heater_degc_per_h: 10 } } }
start: "2026-03-01T08:00:00Z"
duration: 2d
timeline:
  - { at: 6h,  do: actuator_weak, device: inc-heater, fraction: 0 }
  - { at: 30h, do: actuator_weak, device: inc-heater, fraction: null }
  - { at: 36h, command: advance_stage, planting: oyster-1 }
expect:
  - { by: 9h,  zone: incubation-chamber, status: no_effect }
  - { at: 2d,  zone: incubation-chamber, status_not: no_effect }
  - { over: all, device: inc-heater, max_continuous_on: 30m }
  - { over: all, no_event: command_failed }
```

- `do:` entries are the simulator's existing fault injections; `command:` entries are hub
  commands. Nothing new can be expressed that the system cannot already do.
- The **runner** (`fsf scenario run`) builds a `MockSystem`, plays the timeline, checks the
  expectations and writes a result: pass or fail per expectation, and the run's database.
- The **result view is the dashboard**: the same zone pages, charts, log and decision trace,
  reading the run's database, with the timeline's events marked. No second set of charts.
- **Scenario library**: the existing Python scenario tests are ported to scenario files
  where they fit, and `pytest` runs every file in `scenarios/`. A scenario made in the
  studio is then a regression test by being saved.
- **Check a change against scenarios.** A draft can be run against every scenario of its
  site; the apply step shows the outcome.
- **Simulated environments are guesses.** The environment numbers (how fast a chamber loses
  heat, how much a dose wets a pot) are not measured from a real site. The studio says so
  on every result. Fitting them from a real site's recorded data is worth doing later and
  is out of scope here.

Where it runs: the full runner needs a laptop-class machine for long grows. On the hub SBC
the studio offers validation always and **short what-if runs** only (bounded simulated
time and wall time), so a simulation can never starve the control loop. That limit is
measured, not assumed, before it is set (phase S3).

## 6. Manage: changing a live site

The flow, on the hub or pushed from the desktop:

```
draft -> validate -> diff and impact -> (simulate) -> apply -> watch -> keep or roll back
```

1. **Validate**: schemas and cross-references, pins, the safety envelope. A draft that does
   not validate cannot be applied.
2. **Diff and impact**: what changes, sorted by what it costs:

   | Class | Examples | What applying does |
   |---|---|---|
   | Settings | Targets, limits, thresholds, theme, a new planting | Takes effect at the next start of the hub's control loop |
   | Commissioning | A new actuator, an actuator moved to another zone | The zone goes to observe mode until the actuator is bench-tested (already the rule) |
   | Firmware | A device added to a node, a pin changed, calibration changed | The node is marked "firmware out of date"; the hub keeps running the old wiring until the node is reflashed |
   | Structural | A zone or planting removed, a running recipe's stages reordered | Needs an explicit confirmation naming what stops |

3. **Simulate**: optional for settings, required by default for control-loop changes.
4. **Apply**: the hub writes the revision, records who applied it, and restarts its control
   process on the new files. A restart is the first implementation because it is already
   safe by design: actuators hold a lease of a few minutes at most, planting progress and
   dose history are in the database, and a restarted hub resumes where it was (covered by
   existing tests). In-place reload is only worth building if the restart turns out to be
   too disruptive.
5. **Watch**: after applying, the studio shows the affected zones and a "revert" button for
   a set time. A failed start (the new files do not load) falls back to the previous
   revision by itself.
6. **Roll back**: applying the previous revision. Firmware that was flashed is not rolled
   back by this; the impact preview says so.

What applying must never do: switch an actuator on that was off because of it, skip the
observe rule, or change the secrets files.

**Firmware and the hub.** Building ESPHome firmware needs a toolchain of about 1 GB and
minutes of CPU, which does not belong on a small SBC. The hub studio therefore generates
configs and marks nodes out of date; the **desktop studio builds and uploads** (USB the
first time, over the air afterwards). That is one of the two reasons a desktop app is
worth having at all; the other is the simulator.

## 7. The safety envelope

Today a recipe, an override or a goal can set any target. Once editing is a form field
away, that needs a floor and a ceiling that editing cannot cross:

- A **species** gets `limits` per quantity (for example air temperature 10 to 30). A
  recipe, goal or override outside them does not validate.
- A **site** gets hard limits per actuator kind (for example a heater's `max_on` can never
  exceed a site-wide value), which no recipe can raise.
- Limits themselves are edited only by an admin, and a change to them is always in the
  "structural" class.

This is small and should land first: it protects the dashboard's override action today.

## 8. Roles and security

| Role | Can |
|---|---|
| Viewer | Read the dashboard |
| Operator | Everything today's login can: advance, water, pause, override, test pulse |
| Admin | Studio: edit drafts, apply revisions, roll back, edit the site library |

- One password per role to start with (three hashes), not per-person accounts. Names are
  still asked for and logged.
- Every apply and roll back is an event with who, what revision, and the diff summary.
- The studio API writes only inside the site's own folder and its revision store, never the
  built-in catalog on a hub, never secrets.
- **Driver templates are code.** A part's ESPHome template can contain C++ that ends up on
  a node. On a hub, parts and boards are read-only; they are edited in the desktop studio,
  where the person building the firmware can read what they flash.
- The hub's studio is reachable only on the local network, as the dashboard is. Broker
  logins for the studio follow the ACL scheme of `fsf init`: it can ask the hub to act and
  nothing more.

## 9. The desktop app

What it adds over the hub studio:

- The **full simulator**, with speed control and fault injection, for any draft.
- **Offline work** on sites and the library, kept in an ordinary folder (and so in git, if
  the user wants).
- **Firmware**: build, first flash over USB, later uploads over the air.
- **Commissioning tools** with a window instead of a terminal: bench, calibrate, node test.
- **Remotes**: hubs found on the network or added by address. Pull a hub's current
  revision, push a draft to it, compare a hub with a local folder, apply (the hub applies;
  the desktop asks).

Coordination rules between desktop and hub:

- A draft remembers the revision it was based on. A push is refused if the hub has moved on
  since; the user pulls and redoes or merges. No silent overwrite.
- The desktop never talks to nodes of a live site directly except to flash firmware and to
  run the commissioning tools, both of which already go through the hub or announce
  themselves.
- Pulling recorded data from a hub to look at it offline (the database download that
  exists today) is allowed for admins.

### How to package it

The sidecar is the same either way: the Python service, simulator and hub, frozen into
one executable. The question is only the shell around it.

| | Local server + browser | Tauri | Electron |
|---|---|---|---|
| What ships | `fsf studio` starts the service and opens the default browser | Small native shell using the system's web view, plus the sidecar | Chromium and Node, plus the sidecar |
| Size added by the shell | None | Small | Large |
| Rendering | Whatever browser the user has | Differs per OS (three different web view engines) | Identical everywhere |
| USB serial for flashing | Through the Python sidecar | Through the sidecar | Through the sidecar or Node |
| Installers, auto-update, signing | None | Supported; needs a Rust toolchain to build | Mature; JavaScript only |
| Cost to maintain | Lowest | Medium | Medium to high |

**Recommended**: build the desktop studio first as a local server that opens the browser
(`fsf studio`). It needs no new toolchain, proves the sidecar, and is all a developer or an
early user needs. Add a **Tauri** shell when a double-click install matters, because the
frontend is already a static web app and the heavy part is the sidecar in any case. Choose
Electron instead only if the web view differences cost more than they save, which a
one-day trial of both on Windows, macOS and Linux will show.

## 10. Testing

- Round trip: every catalog and site file loads, saves and loads to the same thing, with
  comments kept.
- API tests for drafts, validation, diff classes, revisions, refusal of a stale push.
- Apply and roll back as scenario tests on `MockSystem`: plantings keep their stage, dose
  history survives, a revision that does not load falls back.
- The scenario runner is tested by porting existing Python scenarios and comparing
  outcomes.
- Browser tests: create a site from an example, add a zone and a planting, simulate, apply.
- Desktop: a smoke test that the frozen sidecar starts and serves on each OS.
- The what-if limits on the hub are measured on a Raspberry Pi Zero 2 W.

## 11. Phases

| Phase | Scope | Done when |
|---|---|---|
| S1. Foundations | Safety envelope; layered library; round-trip writing; revision store; roles | Every example file round-trips; an out-of-envelope recipe is rejected; a site can add its own recipe without touching `catalog/` |
| S2. Scenarios as data | `Scenario` schema, runner, results in the dashboard views, existing scenario tests ported | `pytest` runs the scenario files and they agree with the Python tests they replace |
| S3. Local studio | `fsf studio` (local server and browser): site and recipe editors, raw editor, impact preview, run scenarios | A new site is made from an example, changed, simulated and saved without opening a YAML file |
| S4. Hub studio | Studio on the hub: drafts, diff, apply by restart, watch, roll back; short what-if runs with measured limits | A target change is applied to a mock hub and rolled back from a phone; a broken revision falls back by itself |
| S5. Desktop coordination | Remotes, pull, push, compare, stale-push refusal; firmware build and flash; commissioning tools in the UI | A device is added on a laptop, simulated, pushed, applied, and its node reflashed from the app |
| S6. Packaging and the rest | Tauri (or Electron) shell, installers; remaining editors (species, goal, theme, parts, boards) | A person installs the app by double-click on Windows, macOS and Linux and opens an example site |

S1 and S2 are independent. S3 needs both. S4 and S5 need S3 and can overlap. The envelope
in S1 is worth doing even if nothing else here is.

## 12. Decisions needed

1. **Desktop shell.** Recommended: local server and browser first, Tauri later, decided
   after a short trial of Tauri and Electron (section 9).
2. **Where the studio API lives on the hub.** Recommended: inside the dashboard service,
   so there is one login and one port. The alternative, a separate service, isolates a
   studio bug from the dashboard at the cost of a second thing to run on a small SBC.
3. **How applying works.** Recommended: restart the hub's control process on the new
   revision; build in-place reload only if needed.
4. **Writing YAML.** Recommended: round-trip with ruamel.yaml so hand-written comments
   survive. The alternative is a canonical writer: simpler, but the first save reformats a
   file and drops its comments.
5. **Revision store.** Recommended: plain folders with a manifest on the hub (no git on
   the SBC), an ordinary folder on the desktop that the user may put in git.
6. **Roles.** Recommended: three shared passwords (viewer, operator, admin) before any
   per-person accounts.
7. **What "controllers" means.** This plan covers nodes and control loops. If you meant
   custom control strategies beyond the four that exist (dose, hysteresis, duty cycle,
   schedule), that is a larger piece: the hub's control code would need a plugin point,
   and the envelope would have to cover it.
8. **Scenarios replace Python tests, or sit next to them?** Recommended: port what fits
   and keep Python for tests that reach into internals (hub restarts, direct store
   checks).

## 13. Risks

- **Scope.** This is as large as the dashboard and installation plans together. S1 to S3
  give most of the value; S4 onwards should wait until a real site exists to manage.
- **A friendly editor makes unsafe changes easy.** The envelope, the impact preview and
  the observe rule are the answer; none of them is optional.
- **Two places to edit one site.** The stale-push rule keeps hub and desktop from
  overwriting each other, at the price of an occasional manual redo.
- **Simulation is trusted more than it deserves.** A passing scenario says the control
  logic does what was intended in a made-up room. It does not say the room is right.
- **Packaging a Python sidecar** for three operating systems, with signing, is routine
  work that tends to take longer than the feature it wraps.
