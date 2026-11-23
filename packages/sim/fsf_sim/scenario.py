"""Scenarios as data (studio plan S2).

A scenario file says what happens to a simulated site and what must then be true:

    kind: Scenario
    id: heater-fails
    duration: 6h
    timeline:
      - { at: 2h, do: actuator_weak, device: inc-heater, fraction: 0 }
    expect:
      - { by: 5h, zone: incubation-chamber, status: no_effect }

It lives in `<site>/scenarios/`. The runner builds a `MockSystem` for that site, plays the
timeline and checks every expectation. `do:` entries act on the simulated world, `command:`
entries are hub commands sent over the bus as an operator would send them. At each moment
the expectations are checked first and the timeline is applied after, so "at 3h" sees the
world before whatever the timeline does at 3h.

A pass says the control logic does what was intended in a made-up room. The environment
numbers are guesses, not measurements of a real site.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from fsf_core import Catalog, ConfigError, Site, find_repo_root, load_site, topics
from fsf_core.durations import seconds
from fsf_hub import Store

from .harness import DEFAULT_START, MockSystem

NOTE = ("The simulated environment is a guess, not measured from a real site. A pass says the control logic "
        "does what was intended in this made-up room; it does not say the room is right.")

ZONE_QUANTITIES = ("air_temperature", "relative_humidity", "co2", "soil_moisture")

# do: -> (required arguments, optional arguments)
ACTIONS = {
    "sensor_dropout": (("device",), ("active",)),
    "sensor_stuck": (("device", "quantity", "value"), ()),
    "node_offline": (("node",), ("active",)),
    "pump_no_flow": (("device",), ("active",)),
    "actuator_ignores": (("device",), ("active",)),
    "actuator_weak": (("device", "fraction"), ()),
    "set_reservoir": (("device",), ("volume_ml", "percent")),
    "set_ambient": ((), ("air_temperature", "relative_humidity")),
    "set_zone": (("zone",), ZONE_QUANTITIES),
    "clear_faults": ((), ()),
    "stop_hub": ((), ()),
    "start_hub": ((), ()),
}
ENTRY_KEYS = ("at", "do", "command", "refused", "result", "note")

# What can be checked of each kind of subject. An entry names one subject and one check
# (an event entry may combine several).
CHECKS = {
    "zone": ("status", "status_not", "active", "active_not", "active_is", "stage", "led", "led_sequence", *ZONE_QUANTITIES),
    "device": ("is_on", "on_between", "max_continuous_on", "on_time", "delivered_ml", "level"),
    "strip": ("brightness",),
    "planting": ("stage", "in_zone"),
    "event": ("count", "min_gap", "rolling", "values", "offsets"),
}
WINDOW_ONLY = ("on_between", "max_continuous_on", "on_time")
MOMENT_ONLY = ("led_sequence",)


def _subject(spec: dict) -> str | None:
    """What an expectation is about. An event entry may also name a zone, to narrow it."""
    if "event" in spec or "no_event" in spec:
        return "event"
    found = [s for s in ("zone", "device", "strip", "planting") if s in spec]
    return found[0] if len(found) == 1 else None
AFTERWARDS = ("max_continuous_on", "on_time", "delivered_ml", "led_sequence", "event")    # worked out from logs at the end
WHEN_KEYS = ("at", "by", "from", "to")


def span(offset: float) -> str:
    """Seconds from the start as 2d 3h, 15m, 0."""
    left, parts = int(round(offset)), []
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60), ("s", 1)):
        if left >= size:
            parts.append(f"{left // size}{unit}")
            left %= size
    return " ".join(parts) or "0"


def merge(base: dict, over: dict) -> dict:
    """`over` laid on `base`, dictionaries merged key by key."""
    out = dict(base)
    for key, value in over.items():
        out[key] = merge(out[key], value) if isinstance(value, dict) and isinstance(out.get(key), dict) else value
    return out


@dataclass
class Scenario:
    id: str
    path: Path
    raw: dict
    site_dir: Path
    site: Site
    catalog: Catalog
    tick: float
    duration: float
    start: datetime

    @property
    def title(self) -> str:
        return self.raw.get("title") or self.id.replace("-", " ")


def find_scenarios(site_dir: str | Path) -> list[Path]:
    return sorted((Path(site_dir) / "scenarios").glob("*.yaml"))


def load_scenario(path: str | Path, catalog: Catalog | None = None) -> Scenario:
    """Read and check one scenario file. Raises ConfigError with every problem found."""
    path = Path(path)
    if not path.is_absolute() and not path.exists():
        path = find_repo_root() / path
    where = path.name
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if path.parent.name != "scenarios" or not (path.parent.parent / "site.yaml").exists():
        raise ConfigError([f"{where}: a scenario file lives in <site>/scenarios/, next to the site.yaml it runs"])
    catalog = catalog or Catalog.load(find_repo_root())
    problems = catalog.schemas.check("Scenario", raw, where)
    if problems:
        raise ConfigError(problems)
    site_dir = path.parent.parent
    site = load_site(site_dir, catalog)
    tick = float(raw.get("tick", 30))
    duration = seconds(raw["duration"])
    start = datetime.fromisoformat(raw["start"].replace("Z", "+00:00")) if "start" in raw else DEFAULT_START
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    scenario = Scenario(raw["id"], path, raw, site_dir, site, catalog, tick, duration, start)
    problems = _problems(scenario, where)
    if problems:
        raise ConfigError(problems)
    return scenario


def _problems(sc: Scenario, where: str) -> list[str]:
    raw, site, out = sc.raw, sc.site, []
    if raw.get("site", site.id) != site.id:
        out.append(f"{where}: site is {raw['site']!r} but the file is in the folder of site {site.id!r}")
    if raw["id"] != sc.path.stem:
        out.append(f"{where}: id {raw['id']!r} must match the file name")
    if sc.duration % sc.tick:
        out.append(f"{where}: duration must be a multiple of the {sc.tick:g} s tick")
    actuators = {d.id for d in site.devices.values() if d.cls == "actuator"}
    strips = {d.id for d in site.devices.values() if "indicator.led_strip" in d.roles}
    statuses = set(site.theme["statuses"])
    commands = set(json.loads((find_repo_root() / "schemas" / "mqtt" / "hub_command.schema.json")
                              .read_text(encoding="utf-8"))["properties"]["name"]["enum"])
    known = {"zone": site.zones, "device": site.devices, "node": site.nodes, "planting": site.plantings,
             "strip": strips, "in_zone": site.zones}

    def moment(value, label: str) -> float | None:
        t = seconds(value)
        if t > sc.duration:
            out.append(f"{label}: {value} is after the end of the run ({raw['duration']})")
        elif t % sc.tick:
            out.append(f"{label}: {value} is not a multiple of the {sc.tick:g} s tick")
        else:
            return t
        return None

    def refers(entry: dict, label: str, keys=("zone", "device", "node", "planting", "strip", "in_zone")) -> None:
        for key in keys:
            if key in entry and entry[key] not in known[key]:
                out.append(f"{label}: unknown {key.replace('in_', '')} {entry[key]!r}")

    for n, entry in enumerate(raw.get("timeline", [])):
        label = f"{where}: timeline/{n}"
        moment(entry["at"], label)
        refers(entry, label)
        if "do" in entry:
            required, optional = ACTIONS[entry["do"]]
            given = [k for k in entry if k not in ENTRY_KEYS]
            for key in required:
                if key not in entry:
                    out.append(f"{label}: {entry['do']} needs {key}")
            for key in given:
                if key not in required + optional:
                    out.append(f"{label}: {entry['do']} does not take {key}")
            if entry["do"] == "set_reservoir" and ("volume_ml" in entry) == ("percent" in entry):
                out.append(f"{label}: set_reservoir needs volume_ml or percent")
            if entry["do"] == "set_zone" and not any(q in entry for q in ZONE_QUANTITIES):
                out.append(f"{label}: set_zone needs at least one of {', '.join(ZONE_QUANTITIES)}")
        elif entry["command"] not in commands:
            out.append(f"{label}: unknown hub command {entry['command']!r}")

    for n, entry in enumerate(raw["expect"]):
        label = f"{where}: expect/{n}"
        if "no_event" in entry and "event" in entry:
            out.append(f"{label}: give event or no_event, not both")
        subject = _subject(entry)
        if subject is None:
            out.append(f"{label}: name one of zone, device, strip, planting, event or no_event")
            continue
        refers(entry, label)
        checks = [k for k in entry if k in CHECKS[subject]]
        modifiers = ("where", "contains", "zone", "event", "no_event") if subject == "event" else (subject,)
        stray = [k for k in entry if k not in CHECKS[subject] + WHEN_KEYS + modifiers + ("note",)]
        if stray:
            out.append(f"{label}: {', '.join(stray)} cannot be checked of a {subject}")
        if subject != "event" and len(checks) != 1:
            out.append(f"{label}: give exactly one check of the {subject}: {', '.join(CHECKS[subject])}")
        if "no_event" in entry and checks:
            out.append(f"{label}: no_event takes no further checks")
        if sum(k in entry for k in ("at", "by")) + ("from" in entry or "to" in entry) > 1:
            out.append(f"{label}: give at, or by, or a window (from, to), not several")
        times = {k: moment(entry[k], label) for k in WHEN_KEYS if k in entry}
        if None not in times.values() and times.get("from", 0) > times.get("to", sc.duration):
            out.append(f"{label}: from is after to")
        windowed = "at" not in entry and "by" not in entry
        for key in checks:
            if key in WINDOW_ONLY and not windowed:
                out.append(f"{label}: {key} is checked over a window (from, to), not at a moment")
            if key in MOMENT_ONLY and "at" not in entry:
                out.append(f"{label}: {key} needs at")
            if isinstance(entry[key], dict) and "share" in entry[key] and not windowed:
                out.append(f"{label}: share is for a window (from, to)")
        if "by" in entry and (subject == "event" or any(k in AFTERWARDS for k in checks)):
            out.append(f"{label}: use at, not by, for this check")
        if "device" in entry and subject == "device" and entry["device"] not in actuators and entry["device"] in site.devices:
            out.append(f"{label}: {entry['device']} is not an actuator")
        for key in ("status", "status_not"):
            if key in entry and entry[key] not in statuses:
                out.append(f"{label}: unknown status {entry[key]!r}")
        for key in ("active", "active_not", "active_is"):
            for status in _names(entry.get(key)):
                if status not in statuses:
                    out.append(f"{label}: unknown status {status!r}")
    return out


def _names(value) -> list[str]:
    return [] if value is None else [value] if isinstance(value, str) else list(value)


# ---------------------------------------------------------------------- results


@dataclass
class Outcome:
    text: str
    ok: bool
    detail: str

    def __str__(self) -> str:
        return f"{'ok  ' if self.ok else 'FAIL'}  {self.text}" + (f"\n        {self.detail}" if self.detail and not self.ok else "")


@dataclass
class ScenarioResult:
    id: str
    title: str
    site: str
    start: datetime
    end: datetime
    tick: float
    timeline: list[dict] = field(default_factory=list)          # {at, t, text, ok, detail}
    expectations: list[Outcome] = field(default_factory=list)
    db_path: str | None = None
    system: MockSystem | None = None                            # kept only when the caller asked for it

    @property
    def passed(self) -> bool:
        return all(e.ok for e in self.expectations) and all(e["ok"] for e in self.timeline)

    def failures(self) -> list[str]:
        return ([f"timeline at {e['at']}: {e['text']}: {e['detail']}" for e in self.timeline if not e["ok"]]
                + [f"{e.text}: {e.detail}" for e in self.expectations if not e.ok])

    def to_dict(self) -> dict:
        return {"id": self.id, "title": self.title, "site": self.site, "passed": self.passed,
                "start": self.start.isoformat(), "end": self.end.isoformat(), "tick": self.tick, "note": NOTE,
                "timeline": self.timeline,
                "expectations": [{"text": e.text, "ok": e.ok, "detail": e.detail} for e in self.expectations]}

    def report(self) -> str:
        lines = [f"scenario {self.id} on site {self.site}: {'passed' if self.passed else 'FAILED'} "
                 f"({span((self.end - self.start).total_seconds())} simulated)"]
        lines += [f"  FAIL  timeline at {e['at']}: {e['text']}\n        {e['detail']}" for e in self.timeline if not e["ok"]]
        lines += [f"  {e}" for e in self.expectations]
        return "\n".join(lines)


# ---------------------------------------------------------------------- one expectation


class _Check:
    def __init__(self, spec: dict, run: "_Run"):
        self.spec, self.run = spec, run
        duration = run.scenario.duration
        if "at" in spec:
            self.mode, self.t0 = "at", seconds(spec["at"])
            self.t1 = self.t0
        elif "by" in spec:
            self.mode, self.t0, self.t1 = "by", 0.0, seconds(spec["by"])
        else:
            self.mode, self.t0, self.t1 = "window", seconds(spec.get("from", 0)), seconds(spec.get("to", duration))
        self.subject = _subject(spec)
        self.key = "event" if self.subject == "event" else next(k for k in spec if k in CHECKS[self.subject])
        self.total = self.good = 0
        self.first_bad: tuple[float, str] | None = None
        self.last = ""
        self.hit: float | None = None
        self.samples: dict[float, float] = {}

    # -- wording
    def text(self) -> str:
        spec, whole = self.spec, self.t0 == 0 and self.t1 == self.run.scenario.duration
        when = (f"at {span(self.t0)}" if self.mode == "at" else f"by {span(self.t1)}" if self.mode == "by"
                else "throughout" if whole else f"from {span(self.t0)} to {span(self.t1)}")
        if self.subject == "event":
            kind = spec.get("event") or spec["no_event"]
            what = f"events {kind}" + (f" in {spec['zone']}" if "zone" in spec else "")
            filters = ([f"{k} {_show(v)}" for k, v in spec.get("where", {}).items()]
                       + [f"{k} contains '{v}'" for k, v in spec.get("contains", {}).items()])
            if filters:
                what += " where " + ", ".join(filters)
            checks = {k: spec[k] for k in CHECKS["event"] if k in spec} or {"count": 0 if "no_event" in spec else {"min": 1}}
            what += ": " + ", ".join(f"{k} {_show(v)}" for k, v in checks.items())
        else:
            what = f"{self.subject} {spec[self.subject]}: {self.key} {_show(spec[self.key])}"
        return f"{when}: {what}"

    # -- every tick
    def observe(self, offset: float) -> None:
        if self.key == "delivered_ml":
            if offset in (self.t0, self.t1):
                self.samples[offset] = self.run.system.sim.actuators[self.spec["device"]].delivered_ml
            return
        if self.key in AFTERWARDS or not self.t0 <= offset <= self.t1 or self.hit is not None:
            return
        ok, seen = self._probe()
        self.total += 1
        self.good += ok
        self.last = seen
        if ok and self.mode == "by":
            self.hit = offset
        if not ok and self.first_bad is None:
            self.first_bad = (offset, seen)

    def _probe(self) -> tuple[bool, str]:
        spec, key, system = self.spec, self.key, self.run.system
        want = spec[key]
        if self.subject == "zone":
            zone = spec["zone"]
            status = self.run.zone_status(zone)
            if key in ("status", "status_not"):
                return (status.get("state") == want) == (key == "status"), f"status was {status.get('state')}"
            if key in ("active", "active_not"):
                active = status.get("active", [])
                found = [s for s in _names(want) if s in active]
                ok = len(found) == len(_names(want)) if key == "active" else not found
                return ok, f"active were {', '.join(active) or 'none'}"
            if key == "active_is":
                active = status.get("active", [])
                return sorted(active) == sorted(_names(want)), f"active were {', '.join(active) or 'none'}"
            if key == "stage":
                return status.get("stage") == want, f"stage was {status.get('stage')}"
            if key == "led":
                led = system.led(zone) or {}
                return all(led.get(k) == v for k, v in want.items()), f"the segment showed {_show({k: led.get(k) for k in want})}"
            value = getattr(system.sim.zones[zone], key)
            return _within(value, want), f"{key} was {value:.1f}" if value is not None else f"the zone has no {key}"
        if self.subject == "device":
            act, now = system.sim.actuators[spec["device"]], system.clock.now()
            on = act.is_on(now)
            if key == "is_on":
                return on == want, f"it was {'on' if on else 'off'}"
            if key == "level":
                return act.level == want, f"level was {act.level:g}"
            local = now.astimezone(self.run.tz).strftime("%H:%M")       # on_between
            return on == (want[0] <= local < want[1]), f"it was {'on' if on else 'off'} at {local}"
        if self.subject == "strip":
            brightness = (system.sim.leds.get(spec["strip"]) or {}).get("brightness")
            return brightness == want, f"brightness was {brightness}"
        stage, zone = self.run.planting(spec["planting"])
        if key == "stage":
            return stage == want, f"stage was {stage}"
        return zone == want, f"it was in {zone}"

    # -- at the end
    def outcome(self) -> Outcome:
        text = self.text()
        if self.key in AFTERWARDS:
            ok, detail = getattr(self, f"_after_{self.key}")()
            return Outcome(text, ok, detail)
        if self.mode == "by":
            return Outcome(text, self.hit is not None,
                           f"first true at {span(self.hit)}" if self.hit is not None else f"never; at the end {self.last}")
        share = self.spec[self.key].get("share") if isinstance(self.spec[self.key], dict) else None
        if self.total == 0:
            return Outcome(text, False, "never checked")
        if share is not None:
            got = self.good / self.total
            return Outcome(text, got >= share, f"inside for {got:.1%} of the time")
        if self.first_bad is None:
            return Outcome(text, True, self.last)
        offset, seen = self.first_bad
        often = f" (and at {self.total - self.good - 1} more ticks)" if self.total - self.good > 1 else ""
        return Outcome(text, False, f"at {span(offset)} {seen}{often}")

    def _bounds(self) -> tuple[datetime, datetime]:
        start = self.run.scenario.start
        first = 0.0 if self.mode == "at" else self.t0
        return start + timedelta(seconds=first), start + timedelta(seconds=self.t1)

    def _runs(self) -> list[float]:
        """How long the actuator was on each time, clipped to the window, in seconds."""
        lo, hi = self._bounds()
        log, out, began = self.run.system.sim.actuators[self.spec["device"]].log, [], None
        for t, on in [*log, (hi, False)]:
            if on and began is None:
                began = t
            elif not on and began is not None:
                length = (min(t, hi) - max(began, lo)).total_seconds()
                if length > 0:
                    out.append(length)
                began = None
        return out

    def _after_max_continuous_on(self) -> tuple[bool, str]:
        runs = self._runs()
        longest = max(runs, default=0.0)
        limit = seconds(self.spec["max_continuous_on"]) + self.run.scenario.tick     # switched off at the next tick
        return longest <= limit, f"longest run was {span(longest)} of {len(runs)}"

    def _after_on_time(self) -> tuple[bool, str]:
        total, want = sum(self._runs()), self.spec["on_time"]
        ok = ("min" not in want or total >= seconds(want["min"])) and ("max" not in want or total <= seconds(want["max"]))
        return ok, f"it was on for {span(total)}"

    def _after_delivered_ml(self) -> tuple[bool, str]:
        value = self.samples[self.t1] - (self.samples[self.t0] if self.mode == "window" else 0.0)
        return _within(value, self.spec["delivered_ml"]), f"{value:.1f} ml"

    def _after_led_sequence(self) -> tuple[bool, str]:
        zone, (_, until) = self.spec["zone"], self._bounds()
        strip = self.run.scenario.site.zones[zone].indicator["strip"]
        shown: list[str] = []
        for t, by_zone in self.run.system.sim.led_history.get(strip, []):
            if t <= until and (not shown or shown[-1] != by_zone[zone]):
                shown.append(by_zone[zone])
        return shown == self.spec["led_sequence"], f"it showed {', '.join(shown) or 'nothing'}"

    def _after_event(self) -> tuple[bool, str]:
        spec, start = self.spec, self.run.scenario.start
        lo, hi = self._bounds()
        events = [e for e in self.run.events(spec.get("event") or spec["no_event"], spec.get("zone"))
                  if lo <= e["t"] <= hi
                  and all(e.get(k) == v for k, v in spec.get("where", {}).items())
                  and all(v in str(e.get(k, "")) for k, v in spec.get("contains", {}).items())]
        wrong = []
        checks = {k: spec[k] for k in CHECKS["event"] if k in spec} or {"count": 0 if "no_event" in spec else {"min": 1}}
        for key, want in checks.items():
            if key == "count":
                bounds = {"min": want, "max": want} if isinstance(want, int) else want
                if not _within(len(events), bounds):
                    wrong.append(f"there were {len(events)}")
            elif key == "min_gap":
                gaps = [(b["t"] - a["t"]).total_seconds() for a, b in zip(events, events[1:])]
                if gaps and min(gaps) < seconds(want):
                    wrong.append(f"the shortest gap was {span(min(gaps))}")
            elif key == "rolling":
                width = timedelta(seconds=seconds(want["window"]))
                worst = max((sum(o.get(want["field"], 0) for o in events if e["t"] - width < o["t"] <= e["t"]) for e in events),
                            default=0)
                if worst > want["max"]:
                    wrong.append(f"{want['field']} reached {worst:g} within {want['window']}")
            elif key == "values":
                for name, expected in want.items():
                    got = [e.get(name) for e in events]
                    if got != expected:
                        wrong.append(f"{name} was {_show(got)}")
            elif key == "offsets":
                got = [(e["t"] - start).total_seconds() for e in events]
                if got != [seconds(v) for v in want]:
                    wrong.append(f"they happened at {', '.join(span(g) for g in got) or 'no time'}")
        return not wrong, "; ".join(wrong) or f"{len(events)} events"


def _within(value, bounds: dict) -> bool:
    return value is not None and ("min" not in bounds or value >= bounds["min"]) and ("max" not in bounds or value <= bounds["max"])


def _show(value) -> str:
    if isinstance(value, dict):
        return ", ".join(f"{k} {_show(v)}" for k, v in value.items())
    if isinstance(value, list):
        return "[" + ", ".join(_show(v) for v in value) + "]"
    return "none" if value is None else str(value).lower() if isinstance(value, bool) else str(value)


# ---------------------------------------------------------------------- the run


class _Run:
    def __init__(self, scenario: Scenario, db_path: str, record_readings: bool):
        self.scenario = scenario
        site_file = scenario.site_dir / "sim.yaml"
        base = yaml.safe_load(site_file.read_text(encoding="utf-8")) if site_file.exists() else {}
        self.system = MockSystem(scenario.site_dir, db_path=db_path, start=scenario.start, tick=scenario.tick,
                                 record_readings=record_readings, catalog=scenario.catalog,
                                 sim_config=merge(base or {}, scenario.raw.get("environment", {})))
        site = self.system.site
        self.tz = timezone.utc
        if site.timezone != "UTC":
            from zoneinfo import ZoneInfo
            self.tz = ZoneInfo(site.timezone)
        self._zones: dict[str, dict] = {}       # last published status of each zone: still there while the hub is down
        self._hub_state: dict = {}
        self._replies: dict[str, dict] = {}
        bus = self.system.bus
        bus.subscribe(f"{topics.ROOT}/{site.id}/zone/+/status", lambda t, p: self._zones.__setitem__(t.split("/")[3], json.loads(p)))
        bus.subscribe(topics.hub_state(site.id), lambda t, p: self._hub_state.update(json.loads(p)))
        bus.subscribe(topics.hub_reply(site.id), lambda t, p: self._replies.__setitem__(json.loads(p)["id"], json.loads(p)))

    def zone_status(self, zone: str) -> dict:
        hub = self.system.hub
        return hub.zone_status[zone] if hub else self._zones.get(zone, {})

    def planting(self, planting: str) -> tuple[str | None, str | None]:
        """(stage, zone) of a planting; (None, None) once it is finished."""
        hub = self.system.hub
        if hub:
            stage = hub.stage_of(planting)
            return (stage["id"] if stage else None), hub.plantings[planting].zone
        state = self._hub_state.get("plantings", {}).get(planting, {})
        return state.get("stage"), state.get("zone")

    def events(self, kind: str, zone: str | None) -> list[dict]:
        hub = self.system.hub
        if hub:
            return hub.store.events(kind, zone=zone)
        store = Store(self.system.db_path, readonly=True)
        try:
            return store.events(kind, zone=zone)
        finally:
            store.close()

    def apply(self, n: int, entry: dict) -> dict:
        system, sim = self.system, self.system.sim
        args = {k: v for k, v in entry.items() if k not in ENTRY_KEYS}
        shown = " ".join(f"{k}={_show(v)}" for k, v in args.items())
        record = {"at": span(seconds(entry["at"])), "t": system.clock.now().isoformat(), "ok": True, "detail": "",
                  "text": f"{entry.get('do') or entry['command']} {shown}".strip(), "note": entry.get("note")}
        if "command" in entry:
            record["text"] = "command " + record["text"]
            expect_ok = not entry.get("refused", False)
            if not system.hub:
                record.update(ok=False, detail="the hub is stopped, so nothing answered")
                return record
            command = {**args, "name": entry["command"], "id": f"scenario-{n}", "by": "scenario"}
            system.bus.publish(topics.hub_cmd(system.site.id), command)
            reply = self._replies.get(command["id"])
            if reply is None:
                record.update(ok=False, detail="the hub did not answer")
            elif reply["ok"] != expect_ok:
                record.update(ok=False, detail=f"the hub refused it: {reply.get('error')}" if expect_ok
                              else "the hub accepted it, but it was expected to refuse")
            else:
                record["detail"] = _show(reply.get("result")) if reply["ok"] else f"refused: {reply.get('error')}"
                wanted = entry.get("result", {})
                got = reply.get("result") if isinstance(reply.get("result"), dict) else {}
                if any(got.get(k) != v for k, v in wanted.items()):
                    record.update(ok=False, detail=f"the result was {_show(reply.get('result'))}, expected {_show(wanted)}")
            return record
        do = entry["do"]
        if do == "stop_hub":
            if system.hub:
                system.stop_hub()
        elif do == "start_hub":
            if not system.hub:
                system.start_hub()
        elif do == "set_reservoir":
            if args["device"] not in sim.reservoirs:
                record.update(ok=False, detail=f"{args['device']} has no simulated reservoir")
            else:
                volume = args.get("volume_ml")
                if volume is None:
                    volume = sim.reservoirs[args["device"]]["capacity_ml"] * args["percent"] / 100.0
                sim.set_reservoir(args["device"], volume)
        elif do == "set_zone":
            sim.set_zone(args.pop("zone"), **args)
        elif do in ("sensor_dropout", "pump_no_flow", "actuator_ignores"):
            getattr(sim, do)(args["device"], args.get("active", True))
        elif do == "node_offline":
            sim.node_offline(args["node"], args.get("active", True))
        elif do == "sensor_stuck":
            sim.sensor_stuck(args["device"], args["quantity"], args["value"])
        elif do == "actuator_weak":
            sim.actuator_weak(args["device"], args["fraction"])
        else:                                   # set_ambient, clear_faults
            getattr(sim, do)(**args)
        return record


def run_scenario(path: str | Path | Scenario, catalog: Catalog | None = None, out_dir: str | Path | None = None,
                 keep_system: bool = False) -> ScenarioResult:
    """Run one scenario. With `out_dir` the run's database (`hub.db`, with raw readings, for the
    dashboard) and `result.json` are written there; otherwise nothing is left behind."""
    scenario = path if isinstance(path, Scenario) else load_scenario(path, catalog)
    timeline = sorted(enumerate(scenario.raw.get("timeline", [])), key=lambda item: seconds(item[1]["at"]))
    restarts = any(entry.get("do") == "stop_hub" for _, entry in timeline)
    scratch = None
    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        for old in out_dir.glob("hub.db*"):
            old.unlink()
        db_path = str(out_dir / "hub.db")
    elif restarts:                              # a restarted hub must find its database again
        scratch = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        db_path = str(Path(scratch.name) / "hub.db")
    else:
        db_path = ":memory:"

    run = _Run(scenario, db_path, record_readings=out_dir is not None)
    system = run.system
    checks = [_Check(spec, run) for spec in scenario.raw["expect"]]
    result = ScenarioResult(scenario.id, scenario.title, scenario.site.id, scenario.start, scenario.start, scenario.tick,
                            db_path=db_path if out_dir is not None else None)
    try:
        offset, pending = 0.0, list(timeline)
        while True:
            for check in checks:
                check.observe(offset)
            while pending and seconds(pending[0][1]["at"]) <= offset:
                n, entry = pending.pop(0)
                result.timeline.append(run.apply(n, entry))
            if offset >= scenario.duration:
                break
            system.run(scenario.tick)
            offset += scenario.tick
        if system.hub:
            system.hub.store.commit()
        result.end = system.clock.now()
        result.expectations = [check.outcome() for check in checks]
        if out_dir is not None:
            (out_dir / "result.json").write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8", newline="\n")
        if keep_system:
            result.system = system
    finally:
        if not keep_system or result.system is None:
            if system.hub:
                system.stop_hub()
            if scratch:
                scratch.cleanup()
    return result
