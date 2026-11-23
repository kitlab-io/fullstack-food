---
name: diagnose-zone
description: Find out why a growing zone is not ok and walk the user through fixing it, using live data from the hub.
---

# Diagnose a zone

Use this when someone says a zone, plant or chamber "is not working", shows a colour on its
LED segment they do not understand, or asks why the system did or did not do something.

Everything you need is read-only. Never publish to a device topic, never edit the database.
If an action is needed (pause, water, advance, test pulse), tell the person which button on
the dashboard does it, or send a hub command only when they ask you to.

## 1. Get the facts

The dashboard service answers on `http://<hub>:8080`. If it needs a login, ask the person
to do this in their browser instead; do not ask for the password.

| Question | Where |
|---|---|
| What is wrong, and where? | `GET /api/zones`: `status`, `active`, readings against their bands |
| Why is the hub doing what it does? | `GET /api/zones/<zone>`: `decisions` (one per control loop, with reason and inputs) |
| What happened before? | `GET /api/log?zone=<zone>&level=info&limit=100` |
| Which part is quiet or untested? | `GET /api/devices`: `age_s`, `unacked`, `driver_status`, `commissioning` |
| Is a node sending rubbish? | `GET /api/mqtt/recent?topic=<device>`: `errors` lists schema violations |
| What does a status mean? | `GET /api/help/<status>`: what the hub is doing, causes, checks, when it clears |

Without the dashboard, run `fsf doctor --site <site> --mqtt-host <broker> --db <hub db>`
on the hub host. It prints one line per check with the fix for each failure.

## 2. Work from the status

1. Take the zone's `status` (the highest-priority one) and every entry in `active`.
2. For each, read `/api/help/<status>`. Start with the highest-priority one: fixing it
   often clears the others (a silent sensor explains a loop that is off; a dead pump
   explains dry soil).
3. Before listing causes, check which ones the data already rules in or out:
   - `sensor_stale`, `sensor_fault`: which device? `/api/devices` shows the one whose
     `age_s` is large; the `detection` event in the log names the device and the value.
   - `no_effect`, `actuator_fault`: the `detection` event names the loop or device. Look at
     that device's `unacked` count and its last decisions.
   - `needs_water` that does not clear: is the watering decision `blocked: min_interval`,
     `blocked: max_daily_ml`, `blocked: reservoir_low` or `fail-safe`? Each means
     something different.
   - `offline`, `node_unstable`: `node_status` events in the log show when and how often.
4. Give the person the checks from the guide in order, one at a time, cheapest first, and
   ask what they see before moving on.

## 3. Say what you found

- Lead with what is wrong and the single most likely cause.
- Quote the reading or event that shows it, with its time.
- Say what the hub is doing meanwhile (from `doing`), so they know whether anything is at
  risk: for example a heater that is held off, or pumps that are blocked.
- Say how they will know it is fixed (from `clears`).

## What not to conclude

- Hardware advice in the guides is from general experience and has not been confirmed on a
  bench. Say so when it matters (wiring, voltages, currents).
- A zone in observe mode switches nothing by design. "The pump never runs" there is not a
  fault: check `observing` on the zone first.
- A status on a simulated site (`runtime: sim`) says nothing about real hardware.
