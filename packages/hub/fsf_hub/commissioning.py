"""Commissioning tools: bench-test one device, calibrate it, and run a zone acceptance.

They talk to nodes and to the running hub over MQTT only. Results are recorded by the hub
(`commission` command), so the hub's store stays the one place that knows what has been
tested. The order is the installation plan's: bench, calibrate, node test, observe, zone
test, then switch the zone to active.

Every class takes `wait(seconds)`, which must let that much time pass and deliver bus
messages (sleep-and-poll against a broker, advance the virtual clock in tests), and where
a person is involved an `ask` object with say(text), confirm(question) -> bool and
number(question) -> float.
"""

from __future__ import annotations

import copy
import json
import uuid
from datetime import timedelta
from typing import Callable

from fsf_core import topics
from fsf_core.catalog import Catalog, Device, Planting, Site
from fsf_core.nodetest import Check
from fsf_core.recipes import scale_stage

from .hub import Hub
from .store import Store


class CommissioningError(Exception):
    pass


class HubClient:
    """Send operator commands to the running hub and wait for its reply."""

    def __init__(self, site_id: str, bus, wait: Callable[[float], None], by: str = "fsf", reply_within_s: float = 10.0):
        self.site_id, self.bus, self.wait, self.by, self.reply_within_s = site_id, bus, wait, by, reply_within_s
        self._replies: dict[str, dict] = {}
        self.state: dict | None = None
        bus.subscribe(topics.hub_reply(site_id), self._on_reply)
        bus.subscribe(topics.hub_state(site_id), self._on_state)

    def _on_reply(self, topic: str, payload: bytes) -> None:
        reply = json.loads(payload)
        self._replies[reply.get("id", "")] = reply

    def _on_state(self, topic: str, payload: bytes) -> None:
        self.state = json.loads(payload)

    def call(self, name: str, **fields) -> dict | None:
        command_id = uuid.uuid4().hex[:12]
        self.bus.publish(topics.hub_cmd(self.site_id), {"id": command_id, "name": name, "by": self.by, **fields})
        waited = 0.0
        while command_id not in self._replies:
            if waited >= self.reply_within_s:
                raise CommissioningError(f"the hub did not answer {name}; is it running?")
            self.wait(0.5)
            waited += 0.5
        reply = self._replies[command_id]
        if not reply["ok"]:
            raise CommissioningError(f"the hub refused {name}: {reply.get('error')}")
        return reply.get("result")

    def observing(self, zone_id: str) -> str | None:
        waited = 0.0
        while self.state is None and waited < self.reply_within_s:
            self.wait(0.5)
            waited += 0.5
        if self.state is None:
            raise CommissioningError("no hub state on the bus; is the hub running?")
        return self.state.get("observing", {}).get(zone_id)


class _DeviceTool:
    def __init__(self, site: Site, catalog: Catalog, device_id: str, bus, wait: Callable[[float], None], ask, hub: HubClient,
                 report_within_s: float = 150.0):
        if device_id not in site.devices:
            raise CommissioningError(f"site {site.id} has no device {device_id!r}")
        self.site, self.catalog, self.bus, self.wait, self.ask, self.hub = site, catalog, bus, wait, ask, hub
        self.dev: Device = site.devices[device_id]
        self.report_within_s = report_within_s
        self.reports: list[dict] = []
        bus.subscribe(topics.device(site.id, self.dev.node, self.dev.id, "state"), self._on_state)

    def _on_state(self, topic: str, payload: bytes) -> None:
        try:
            self.reports.append(json.loads(payload))
        except ValueError:
            pass

    def _next_reports(self, count: int, within: float | None = None) -> list[dict]:
        """Wait for `count` new state messages."""
        start, waited, limit = len(self.reports), 0.0, within or self.report_within_s
        while len(self.reports) < start + count and waited < limit:
            self.wait(1.0)
            waited += 1.0
        return self.reports[start:]

    def _quantities(self) -> list[str]:
        components = self.catalog.items["Component"]
        return [m["quantity"] for role in self.dev.roles for m in components[role].get("measures", [])]

    def _record(self, step: str, checks: list[Check], data: dict) -> None:
        ok = all(c.ok for c in checks)
        self.hub.call("commission", scope="device", subject=self.dev.id, step=step, ok=ok,
                      data={**data, "checks": [{"name": c.name, "ok": c.ok, "detail": c.detail} for c in checks]})


class Bench(_DeviceTool):
    """Stage 1: prove one device before anything depends on it."""

    def run(self) -> list[Check]:
        spec = self.dev.model.get("bench_test")
        if spec is None:
            raise CommissioningError(f"model {self.dev.model['id']} has no bench_test in the catalog")
        checks = self._actuator(spec) if self.dev.cls == "actuator" else self._sensor(spec)
        self._record("bench", checks, {})
        return checks

    def _sensor(self, spec: dict) -> list[Check]:
        wanted = self._quantities()
        got = self._next_reports(2)
        checks = [Check(f"{self.dev.id} reports continuously", len(got) >= 2,
                        f"{len(got)} report(s) in {self.report_within_s:g} s")]
        if not got:
            return checks
        latest = got[-1]
        for quantity in wanted:
            value = latest.get(quantity)
            low, high = spec.get("plausible", {}).get(quantity, (None, None))
            if not isinstance(value, (int, float)):
                checks.append(Check(f"{quantity} is reported", False, f"last report: {latest}"))
            elif low is not None:
                checks.append(Check(f"{quantity} is plausible", low <= value <= high, f"{value} (expected {low} to {high})"))
        # The stimulus: something a person does that the sensor must notice.
        baseline = {q: latest[q] for q in wanted if isinstance(latest.get(q), (int, float))}
        jitter = {q: abs(got[-1].get(q, 0) - got[0].get(q, 0)) if len(got) > 1 else 0.0 for q in baseline}
        self.ask.say(f"{spec['stimulus']}. Expected: {spec['expect']}.")
        moved = None
        for report in self._next_reports(3, within=self.report_within_s * 2):
            for quantity, before in baseline.items():
                low, high = spec.get("plausible", {}).get(quantity, (before - 50, before + 50))
                threshold = max(0.02 * (high - low), 4 * jitter[quantity])
                after = report.get(quantity)
                if isinstance(after, (int, float)) and abs(after - before) > threshold:
                    moved = f"{quantity} went from {before} to {after}"
            if moved:
                break
        checks.append(Check(f"{self.dev.id} responds to the stimulus", moved is not None,
                            moved or "no reported quantity changed clearly"))
        return checks

    def _actuator(self, spec: dict) -> list[Check]:
        pulse = float(spec.get("pulse_s", 2))
        self.ask.say(f"{spec['stimulus']}. Expected: {spec['expect']}.")
        try:
            self.hub.call("actuator_test", device=self.dev.id, duration_s=pulse)
        except CommissioningError as err:
            return [Check(f"{self.dev.id} accepts a test pulse", False, str(err))]
        waited = 0.0
        while not (self.reports and self.reports[-1].get("on") is False) and waited < pulse + 10:
            self.wait(1.0)
            waited += 1.0
        off = bool(self.reports) and self.reports[-1].get("on") is False
        seen_on = any(r.get("on") is True for r in self.reports)
        return [Check(f"{self.dev.id} reports on, then off after {pulse:g} s", seen_on and off, f"last state: {self.reports[-1:]}"),
                Check(f"{self.dev.id} did what was expected", self.ask.confirm(f"{spec['expect']}?"), "as judged by the builder")]


class Calibrate(_DeviceTool):
    """Stage 2: measure the values a device needs in the site file. Prints them; never edits the file."""

    def run(self) -> tuple[list[Check], dict]:
        spec = self.dev.model.get("calibration")
        if spec is None:
            raise CommissioningError(f"model {self.dev.model['id']} needs no calibration")
        procedure = getattr(self, f"_{spec['procedure']}", None)
        if procedure is None:
            raise CommissioningError(f"calibration procedure {spec['procedure']} is done by hand: {spec.get('notes', '')}")
        checks, values = procedure()
        self._record("calibration", checks, {"values": values})
        return checks, values

    def _raw(self, prompt: str) -> float | None:
        """Mean of the raw value over the next two reports after the builder has set things up."""
        self.ask.say(prompt)
        if not self.ask.confirm("Ready"):
            return None
        self._next_reports(1)                           # let one report from before the change go by
        values = [r["raw"] for r in self._next_reports(2) if isinstance(r.get("raw"), (int, float))]
        return round(sum(values) / len(values), 3) if values else None

    def _two_points(self, first: tuple[str, str], second: tuple[str, str], apart: float, unit: str) -> tuple[list[Check], dict]:
        a = self._raw(first[1])
        b = self._raw(second[1]) if a is not None else None
        checks = [Check(f"{self.dev.id} reports a raw value", a is not None and b is not None,
                        "" if a is not None and b is not None else "no `raw` in its state messages")]
        if a is None or b is None:
            return checks, {}
        checks.append(Check("the two readings are clearly apart", abs(a - b) >= apart,
                            f"{a} {unit} and {b} {unit} (need at least {apart} {unit} between them)"))
        return checks, {first[0]: a, second[0]: b}

    def _soil_dry_wet(self):
        return self._two_points(("dry_v", "Hold the probe in dry air"),
                                ("wet_v", "Stand the probe in a glass of water up to the line"), 0.3, "V")

    def _level_empty_full(self):
        return self._two_points(("empty_cm", "Empty the reservoir down to the lowest level you want to allow"),
                                ("full_cm", "Fill the reservoir to its full mark"), 3.0, "cm")

    def _pump_timed_run(self):
        seconds_on = 10.0
        self.ask.say("Prime the tube, then put the outlet in a measuring cup")
        if not self.ask.confirm("Ready"):
            return [Check("pump run", False, "cancelled")], {}
        try:
            self.hub.call("actuator_test", device=self.dev.id, duration_s=seconds_on)
        except CommissioningError as err:
            return [Check(f"{self.dev.id} accepts a timed run", False, str(err))], {}
        self.wait(seconds_on + 2)
        volume = self.ask.number(f"Millilitres delivered in {seconds_on:g} s")
        flow = round(volume / seconds_on, 2)
        return [Check("the pump delivered water", volume > 0, f"{volume} ml in {seconds_on:g} s")], {"flow_ml_per_s": flow}

    def _led_segment_check(self):
        cmd = topics.device(self.site.id, self.dev.node, self.dev.id, "cmd")
        before = self.reports[-1] if self.reports else None
        checks = []
        for zone in self.site.zones.values():
            if not zone.indicator or zone.indicator["strip"] != self.dev.id:
                continue
            segment = {"zone": zone.id, "leds": zone.indicator["leds"], "status": "ok", "color": [0, 0, 0, 60], "effect": "solid"}
            self.bus.publish(cmd, {"id": uuid.uuid4().hex[:12], "name": "render", "brightness": 0.3, "segments": [segment]})
            self.wait(1.0)
            first, last = zone.indicator["leds"]
            checks.append(Check(f"segment of {zone.id} is where it should be",
                                self.ask.confirm(f"LEDs {first} to {last} are lit white, and they are the ones at {zone.id}"),
                                "as judged by the builder"))
        if before and "segments" in before:             # put back what the hub was showing
            self.bus.publish(cmd, {"id": uuid.uuid4().hex[:12], "name": "render", "brightness": before.get("brightness", 0),
                                   "segments": before["segments"]})
        return checks, {}


class ZoneAcceptance:
    """Stage 5: run one zone's recipe stage for real, shortened, and check that every loop works.

    A second, headless hub drives only this zone while the real hub keeps it in observe
    mode. Durations in the stage (for, min_interval, max_on, duty cycles) are divided by
    `speed`; dose volumes and target bands are not changed.
    """

    def __init__(self, site: Site, catalog: Catalog, zone_id: str, bus, clock, wait: Callable[[float], None],
                 hub: HubClient, stage: str | None = None, speed: float = 60.0, run_s: float = 1800.0, tick_s: float = 5.0):
        if zone_id not in site.zones:
            raise CommissioningError(f"site {site.id} has no zone {zone_id!r}")
        self.site, self.catalog, self.zone, self.bus, self.clock, self.wait, self.hub = site, catalog, zone_id, bus, clock, wait, hub
        self.speed, self.run_s, self.tick_s = speed, run_s, tick_s
        role = site.zones[zone_id].role
        found = None
        for planting in site.plantings.values():
            for candidate in planting.recipe["stages"]:
                fits = candidate.get("zone_role") in (None, role) and (planting.zone == zone_id or candidate.get("zone_role") == role)
                if fits and candidate["control"] and stage in (None, candidate["id"]) and found is None:
                    found = (planting, candidate)
        if found is None:
            raise CommissioningError(f"no planting has a stage{' ' + repr(stage) if stage else ''} with control loops for zone {zone_id}")
        self.planting, self.stage = found[0], scale_stage(found[1], speed)

    def _site(self) -> Site:
        trial = copy.copy(self.site)
        recipe = {**self.planting.recipe, "stages": [self.stage]}
        trial.plantings = {self.planting.id: Planting(id=self.planting.id, zone=self.zone, species=self.planting.species,
                                                      recipe=recipe, raw=self.planting.raw)}
        return trial

    def run(self) -> list[Check]:
        why = self.hub.observing(self.zone)
        if not why:
            raise CommissioningError(f"zone {self.zone} is not in observe mode on the hub; run `fsf zone mode {self.zone} observe` "
                                     "first, or two hubs would fight over it")
        store = Store()
        runner = Hub(self._site(), self.catalog, self.bus, self.clock, store, zones={self.zone}, headless=True)
        runner.start()
        started = self.clock.now()
        seen: set[str] = set()
        try:
            while (self.clock.now() - started).total_seconds() < self.run_s:
                runner.tick()
                seen |= set(runner.zone_status[self.zone]["active"])
                self.wait(self.tick_s)
        finally:
            for dev in self.site.zone_devices(self.zone, cls="actuator"):      # leave everything off
                runner._send(dev, {"name": "off"})
            self.wait(1.0)
            runner.stop()
        checks = self._judge(store, started, seen)
        self.hub.call("commission", scope="zone", subject=self.zone, step="zone_test", ok=all(c.ok for c in checks),
                      data={"stage": self.stage["id"], "speed": self.speed, "run_s": self.run_s,
                            "checks": [{"name": c.name, "ok": c.ok, "detail": c.detail} for c in checks]})
        return checks

    def _judge(self, store: Store, started, seen: set[str]) -> list[Check]:
        checks = [Check("sensors reported and nodes stayed online throughout", not seen & {"sensor_stale", "offline"},
                        ", ".join(sorted(seen & {"sensor_stale", "offline"})))]
        devices = {d.id for d in self.site.zone_devices(self.zone, cls="actuator")}
        unanswered = [c for c in store.commands(unacked=True) if c["device"] in devices]
        refused = [e for e in store.events("command_failed") if e["device"] in devices]
        checks.append(Check("every command was acknowledged", not unanswered and not refused,
                            f"{len(unanswered)} unanswered, {len(refused)} refused"))
        for loop in self.stage["control"]:
            for dev in self.site.zone_devices(self.zone, role=loop["actuator"]):
                trace = [d for d in store.decisions(zone=self.zone, loop=loop["id"]) if d["device"] == dev.id]
                ons = [d for d in trace if d["action"] == "on"]
                checks.append(Check(f"loop {loop['id']} switched {dev.id} on", bool(ons),
                                    f"{len(ons)} time(s)" if ons else f"never; last reason: {trace[-1]['reason'] if trace else 'none'}"))
                effect = self._effect(store, loop, ons[0]["t"] if ons else None)
                if effect:
                    checks.append(effect)
        limits = [e["device"] for e in store.events("limit")]
        if limits:
            checks.append(Check("max_on limits were enforced", True, ", ".join(sorted(set(limits)))))
        return checks

    def _effect(self, store: Store, loop: dict, since) -> Check | None:
        """After the loop first acted, did its quantity move the way the loop pushes it?"""
        if loop["strategy"] == "hysteresis":
            quantity, rising = loop["quantity"], loop["direction"] == "raise"
        elif loop["strategy"] == "dose":
            quantity, rising = loop["trigger"]["quantity"], "below" in loop["trigger"]
        elif "also_when" in loop:
            quantity, rising = loop["also_when"]["quantity"], False
        else:
            return None
        name = f"loop {loop['id']} moved {quantity} {'up' if rising else 'down'}"
        if since is None:
            return Check(name, False, "the loop never acted")
        sensor = next((d for d in self.site.zone_devices(self.zone, cls="sensor")
                       if store.readings(d.id, quantity)), None)
        samples = store.readings(sensor.id, quantity, since - timedelta(seconds=90)) if sensor else []
        if len(samples) < 2:
            return Check(name, False, "not enough readings after it acted")
        before = samples[0][1]
        best = max(v for _, v in samples) if rising else min(v for _, v in samples)
        needed = max(0.5, 0.02 * abs(before))
        moved = (best - before) if rising else (before - best)
        return Check(name, moved >= needed, f"{before:g} -> {best:g} (needs a change of at least {needed:g})")
