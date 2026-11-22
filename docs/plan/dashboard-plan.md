# Web dashboard plan

Status (2026-11-22): the recommended options in section 9 are accepted. Phases D1 and D2
are built; D3 to D5 are not started. It builds on the hub, simulator and
MQTT contract described in `AGENTS.md`.

How D1 differs from the text below:

- The decision trace stores a row when a loop's decision changes (want, action or reason),
  not one per tick. The reading and setpoint at that moment are stored with it.
- `water_now` skips the trigger and `min_interval` (otherwise it could rarely do anything)
  but keeps the reservoir interlock and `max_daily_ml`, cannot exceed the recipe's own dose,
  and counts towards the interval and cap of later automatic doses.
- An override applies to one target band of the current stage and is dropped when the
  stage advances. `clear_override` was added.
- The command log is trimmed together with the decision trace.
- "Database size stays bounded" is tested for the detailed tables; rollups and events grow
  slowly by design.
- The mock stack's database is `/data/mock.db` on the `mock-data` volume, emptied at each
  start (`--reset-db`).

How D2 stands:

- `packages/web`: `fsf_web` (FastAPI, GET only) and a Vue 3 + Vite + uPlot frontend with
  three pages: zones overview, zone detail (readings against bands, charts with the target
  band and stage marks, actuator timeline, the latest decision per loop, LED preview) and
  devices. Live updates over one SSE stream. No CDN assets; system fonts.
- It is in the Docker image and both compose files, on `127.0.0.1:8080`. There is no login
  yet (D4), so it is not published to the network.
- Checked by API tests against a `MockSystem` and by hand in a browser against the mock
  stack (mushrooms and house plants; desktop and phone width). There are no browser tests
  yet (section 7), and the Pi Zero performance budget has not been measured.
- Not in D2: which layer set each target (the resolved recipe does not record it), stage
  durations on the stage timeline, per-status troubleshooting links, commissioning state.
- The decision trace now also stores a row when a loop's setpoint changes, so the "why"
  panel shows the target in force.

## 1. Goals

1. See at a glance what every growing area needs, using the same status vocabulary and
   colours as the LED strips.
2. Answer "why did it do that?" without reading code: every watering, stage change, limit,
   interlock and status change is visible with the readings and setpoints that caused it.
3. Give developers and builders raw access: live MQTT traffic, stored readings, the event
   log, and exports.
4. Work fully offline on the local network, on a phone, and against the mock stack.

Non-goals for the first version: editing site or recipe YAML in the browser, user accounts
beyond one shared login, cloud access.

## 2. Architecture

```
browser  <-- HTTP + SSE -->  web service  -- reads -->  hub SQLite (WAL, read-only)
                                  |
                                  +-- MQTT subscribe fsf/<site>/# (live view, raw log)
                                  +-- MQTT publish  fsf/<site>/hub/cmd (all actions)
```

- **New package `packages/web`**: a FastAPI service (`fsf_web`) plus a Vue 3 + Vite
  frontend built to static files that the service serves. One extra container.
- **Reads** come from the hub's SQLite file opened read-only (the store already uses WAL),
  and from MQTT for anything live.
- **Writes never touch the database or devices directly.** Every action is published as a
  hub command, so recipe limits, interlocks and leases apply exactly as they do for
  automatic control. The hub answers on a reply topic so the UI can show accepted/rejected.
- **Live updates** use Server-Sent Events: one stream bridging MQTT messages to the browser.
  It is simpler than WebSockets and enough for one-way push.
- **No CDN assets.** Fonts, charts and icons are bundled so the page loads with no internet.
- Charts: uPlot (small, fast with tens of thousands of points). Reuse nothing from the
  `flask-vue-crud` tutorial scaffold except the idea of `LineChart.vue`; delete the scaffold
  when this lands.

Alternative considered: serve HTTP from inside the hub process. Rejected because the hub is
deliberately thread-free and tick-driven, and a web bug should not be able to stall control.

## 3. Hub changes this needs

These are prerequisites, each small and testable in the existing scenario suite.

| Change | Why |
|---|---|
| Decision trace: per tick and loop, record inputs, setpoint, decision and reason (`want on`, `blocked: min_interval until 14:02`, `blocked: reservoir_low`, `fail-safe: reading stale`) | Powers the "why" view. Kept in a bounded table, see retention |
| Store commands sent and acks received, linked by command id | Actuator timeline and failed-command detection |
| New hub commands: `water_now`, `set_override` (temporary target override with expiry), `pause_zone` / `resume_zone`, `actuator_test` (short leased pulse) | Dashboard actions and commissioning |
| Command replies on `fsf/<site>/hub/reply` with the request id, `ok`, and `error` | UI feedback |
| Retained `fsf/<site>/hub/state`: plantings (stage, started, ready), per-actuator state, hub version, tick duration | Lets the web service start without replaying history |
| Log levels on events (`debug`, `info`, `warn`, `error`) | Filtering in the verbose log |
| Retention job: raw readings kept N days, then 5-minute and hourly min/mean/max rollups; decision trace kept N days; events kept forever | Bounded database on an SD card |
| Mock stack writes the hub database to a per-run volume instead of `:memory:` | So the dashboard has data in mock mode |

## 4. Views

### 4.1 Overview

One card per zone, ordered by status priority (problems first).

- Status name, colour and effect taken from the site's theme, so the card matches the LED
  segment. Every status also has an icon and text; colour is never the only signal.
- Planting, stage, day N of M, and time until the stage is due.
- Key readings against their bands as small bullet bars.
- Reservoir level, node online/offline, time of last reading.
- Banner for anything that needs a person: `stage_ready`, `reservoir_low`, `offline`,
  `sensor_stale`, each linking to its troubleshooting guide (see the installation plan).

### 4.2 Zone detail

- Time-series chart per quantity with the target band shaded and stage boundaries marked.
  Ranges: 6 h, 24 h, 7 d, whole grow. Rollups are used automatically for long ranges.
- Actuator timeline under the charts: on/off bars per device, doses as markers with volume.
- Stage timeline for staged recipes with typical/min/max durations.
- Setpoint trace: resolved targets and control loops for the current stage, and which layer
  (species, recipe, goal, override) set each value.
- "Why" panel: the latest decision trace per loop in plain language, with history.
- Actions: advance stage (with the hint from the recipe and a confirmation that names the
  destination zone), water now, temporary override, pause zone.
- LED preview showing what the segment is displaying and the legend.

### 4.3 Devices and nodes

- Per node: online state, last seen, runtime, firmware version, board.
- Per device: model, role, last value, age of last reading, calibration, commissioning state,
  driver test status from the catalog (`verified`, `bench`, `untested`).
- Per actuator: current state, lease remaining, on-time today, switch count today,
  "test pulse" button.

### 4.4 Verbose log

A filterable, live-tailing table over the event log and decision trace.

- Filters: level, kind (dose, stage, status, limit, interlock, node, command, decision),
  zone, device, planting, time range, free text.
- Each row expands to the full JSON record.
- A row links to the zone chart at that moment.
- Follow mode with pause; export the filtered result as JSON Lines or CSV.

### 4.5 Raw data

For developers and for debugging a real node.

- **MQTT live tail**: every message under `fsf/<site>/#` with topic filter, pause, retained
  flag, pretty-printed payload, and a badge when a payload fails its schema in
  `schemas/mqtt/`. Buffer the last few thousand messages in the web service so opening the
  page shows recent traffic.
- **Readings browser**: pick device, quantity and range; table plus chart of raw samples
  (no rollup); CSV export.
- **Publish tool** (developer mode only, off by default): send a hub command by form.
  It cannot publish to device topics, so it cannot bypass the hub.
- **Downloads**: snapshot of the SQLite database, and a diagnostics bundle (site config with
  secrets redacted, last 24 h of events, hub state).

### 4.6 System

Hub version and uptime, tick duration, broker connection, database size and oldest record,
last backup time, catalog validation result for the running site.

### 4.7 Simulator controls (mock stack only)

Shown only when the simulator announces itself on the bus: speed, pause, current simulated
time, and buttons for the existing fault injections (sensor dropout, stuck sensor, node
offline, empty reservoir, ambient temperature). This turns the mock stack into a demo and a
manual test bench.

## 5. API sketch

```
GET  /api/site                          resolved site: zones, devices, plantings, theme
GET  /api/zones                         current status of every zone
GET  /api/zones/{id}/series?quantity=&from=&to=&resolution=auto|raw|5m|1h
GET  /api/zones/{id}/actuators?from=&to=
GET  /api/zones/{id}/trace              resolved setpoints with layers; latest decisions
GET  /api/events?level=&kind=&zone=&device=&from=&to=&q=&limit=&after=
GET  /api/readings?device=&quantity=&from=&to=&format=json|csv
GET  /api/mqtt/recent?topic=            buffered raw messages
GET  /api/stream                        SSE: zone status, device state, events, raw mqtt (by subscription)
POST /api/commands                      {name, ...} -> published to hub/cmd; returns the hub reply
GET  /api/export/db, /api/export/diagnostics
```

Responses are described by JSON Schemas kept next to the others in `schemas/`, so the agent
docs and the frontend types are generated from one place.

## 6. Security

- Bind to the LAN only; never exposed to the internet.
- One shared login (password hash in `sites/local/secrets.yaml`), session cookie. Read-only
  without login is a per-site setting, off by default.
- All state-changing requests require login and a CSRF token; every command is logged with
  who sent it.
- Publish tool and database download are behind a developer-mode flag.
- Broker credentials for the web service are read-only on device topics and write-only on
  `hub/cmd` once ACLs exist (plan phase 6).

## 7. Testing

- API tests run the web service against a `MockSystem` database and the in-memory bus.
- Scenario tests gain assertions on the new hub features (decision trace reasons, command
  replies, overrides expiring, pause).
- Browser tests (Playwright) run against the Docker mock stack: overview shows the right
  statuses, a fault injected from the simulator panel appears in the UI, an advance-stage
  click moves the planting, raw tail shows traffic.
- Performance budget: zone detail for a 21-day grow loads in under one second on a
  Raspberry Pi Zero 2 W; verify with a seeded database.

## 8. Phases

| Phase | Scope | Done when |
|---|---|---|
| D1. Hub groundwork | Decision trace, command/ack storage, replies, `hub/state`, log levels, retention, mock database on a volume | New scenario assertions pass; database size stays bounded in a 60-day simulated run |
| D2. Read-only dashboard | Web service, overview, zone detail charts, devices page, live updates | `just mock` serves the dashboard and all three example sites render correctly |
| D3. Verbose log and raw data | Event log view, MQTT tail with schema badges, readings browser, exports | A stale-sensor fault can be diagnosed from the UI alone |
| D4. Actions | Advance stage, water now, override, pause, test pulse, login | Browser tests drive a full mushroom grow through the UI |
| D5. Simulator panel and polish | Fault injection from the UI, phone layout, accessibility pass, performance check on a Pi | Demo script in the README works end to end |

D2 and D3 can overlap once D1 is in.

## 9. Decisions needed

1. **Separate web service vs inside the hub.** Recommended: separate (section 2).
2. **FastAPI + Vue 3.** Vue matches the existing scaffold; say so if you prefer something else.
3. **Home Assistant overlap.** With HA present, HA dashboards can show the same entities via
   MQTT discovery. Recommended: still build this dashboard, because the log, decision trace
   and raw views have no HA equivalent, and HA stays optional.
4. **Retention defaults.** Proposed: raw readings 30 days, decision trace 14 days, rollups
   and events forever.
