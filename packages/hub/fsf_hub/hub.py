"""The hub: reads device state from the bus, runs each zone's recipe stage, drives
actuators within safety limits, and publishes zone status and LED renders.

The hub is driven by tick(): call it every 30 s or so with any Clock. It keeps no
threads of its own, which is what lets tests run it against a virtual clock.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fsf_core import topics
from fsf_core.catalog import Catalog, Device, Planting, Site
from fsf_core.durations import seconds

from .store import Store

LOW_STATUS = {"air_temperature": "too_cold", "soil_temperature": "too_cold",
              "relative_humidity": "too_dry", "soil_moisture": "needs_water"}
HIGH_STATUS = {"air_temperature": "too_hot", "soil_temperature": "too_hot",
               "relative_humidity": "too_humid", "soil_moisture": "too_wet", "co2": "stale_air"}
DEFAULT_MIN_OFF = 60.0
STATUS_REPUBLISH = 300.0
DEBOUNCE_GAP = 150.0
RETAIN_EVERY = 3600.0
TEST_PULSE_DEFAULT = 2.0
TEST_PULSE_MAX = 10.0
COMMISSION_SCOPES = ("device", "node", "zone")
COMMISSION_STEPS = ("bench", "calibration", "node_test", "zone_test", "soak")


@dataclass
class PlantingState:
    id: str
    stage_index: int
    stage_started_at: datetime
    zone: str | None            # None once the planting is finished and cleared
    ready: bool = False         # waiting for a person to advance the stage

    def dump(self) -> dict:
        return {"stage_index": self.stage_index, "stage_started_at": self.stage_started_at.isoformat(),
                "zone": self.zone}


@dataclass
class ActuatorState:
    commanded_on: bool = False
    level: float | None = None
    on_since: datetime | None = None
    off_since: datetime | None = None
    lease_until: datetime | None = None
    locked_until: datetime | None = None    # forced off after hitting max_on
    busy_until: datetime | None = None      # a timed dose or test pulse is running

    def dump(self, now: datetime) -> dict:
        def future(t: datetime | None) -> str | None:
            return t.isoformat() if t and t > now else None
        return {"on": self.commanded_on or future(self.busy_until) is not None, "level": self.level,
                "lease_until": future(self.lease_until), "busy_until": future(self.busy_until),
                "locked_until": future(self.locked_until)}


class Hub:
    def __init__(self, site: Site, catalog: Catalog, bus, clock, store: Store | None = None,
                 record_readings: bool = True, zones: set[str] | None = None, headless: bool = False):
        """zones: control only these zones. headless: publish no zone status, hub state or LED
        renders and take no operator commands. Together they let an acceptance run drive one
        zone next to the real hub, which keeps that zone in observe mode meanwhile."""
        self.site, self.bus, self.clock = site, bus, clock
        self.store = store or Store()
        self.record_readings = record_readings
        self._zones, self.headless = zones, headless
        self._runtime = {n["id"]: n["runtime"] for n in site.raw["nodes"]}
        self.observe: set[str] = set()                          # zones an operator put in observe mode
        self.commissioning: dict[tuple[str, str, str], dict] = {}   # (scope, subject, step) -> latest record
        self._observed_last: set[str] = set()
        self._bad_topics: set[str] = set()
        self._observing: dict[str, str | None] | None = None     # cache; cleared when modes or records change
        self._role_quantities = {c["id"]: [m["quantity"] for m in c.get("measures", [])]
                                 for c in catalog.items["Component"].values()}
        self._tz = timezone.utc if site.timezone == "UTC" else _zone(site.timezone)
        self._latest: dict[str, tuple[datetime, dict]] = {}     # device id -> (received at, payload)
        self._node_online: dict[str, bool] = {}
        self._act: dict[str, ActuatorState] = {}
        self._latch: dict[tuple[str, str], bool] = {}           # (zone, loop) -> hysteresis / co2 latch
        self._debounce: dict[tuple, dict] = {}                  # see _held()
        self._led_sent: dict[str, str] = {}
        self._status_sent: dict[str, tuple[str, datetime]] = {}
        self.plantings: dict[str, PlantingState] = {}
        self.zone_status: dict[str, dict] = {}
        self.started_at: datetime | None = None
        self.decisions: dict[tuple[str, str, str], dict] = {}   # (zone, loop, device) -> latest decision
        self.paused: dict[str, str | None] = {}                 # zone -> resume time (ISO) or None for "until resumed"
        self.overrides: dict[str, dict[str, dict]] = {}         # zone -> quantity -> {"values": {...}, "until": ISO}
        self.tick_ms = 0.0
        self._retained_at: datetime | None = None
        self._state_sent: tuple[str, datetime] | None = None
        self._commands = {"advance_stage": self._cmd_advance_stage, "water_now": self._cmd_water_now,
                          "set_override": self._cmd_set_override, "clear_override": self._cmd_clear_override,
                          "pause_zone": self._cmd_pause_zone, "resume_zone": self._cmd_resume_zone,
                          "actuator_test": self._cmd_actuator_test, "set_zone_mode": self._cmd_set_zone_mode,
                          "commission": self._cmd_commission}

    # ------------------------------------------------------------------ lifecycle

    def start(self) -> None:
        now = self.clock.now()
        self.started_at = now
        for planting in self.site.plantings.values():
            saved = self.store.load_planting(planting.id)
            if saved:
                state = PlantingState(planting.id, saved["stage_index"],
                                      datetime.fromisoformat(saved["stage_started_at"]), saved["zone"])
            else:
                state = PlantingState(planting.id, 0, now, planting.zone)
                self.store.save_planting(planting.id, state.dump())
                self.store.event(now, "planting_started", zone=planting.zone, planting=planting.id,
                                 recipe=planting.recipe["id"], layers=planting.recipe["layers"])
            self.plantings[planting.id] = state
        self.paused = {z: until for z, until in self.store.get_setting("paused", {}).items() if z in self.site.zones}
        self.overrides = {z: o for z, o in self.store.get_setting("overrides", {}).items() if z in self.site.zones}
        self.observe = {z for z in self.store.get_setting("observe", []) if z in self.site.zones}
        self.commissioning = {(r["scope"], r["subject"], r["step"]): r for r in self.store.commissioning()}
        self._observing = None
        sid = self.site.id
        self.bus.subscribe(f"{topics.ROOT}/{sid}/+/+/state", self._on_state)
        self.bus.subscribe(f"{topics.ROOT}/{sid}/+/+/ack", self._on_ack)
        self.bus.subscribe(f"{topics.ROOT}/{sid}/+/status", self._on_node_status)
        if not self.headless:
            self.bus.subscribe(topics.hub_cmd(sid), self._on_hub_cmd)

    def stop(self) -> None:
        self.store.commit()
        if hasattr(self.bus, "unsubscribe_all"):
            self.bus.unsubscribe_all(self)

    # ------------------------------------------------------------------ bus handlers

    def _on_state(self, topic: str, payload: bytes) -> None:
        device_id = topic.split("/")[3]
        if device_id not in self.site.devices:
            return
        data = self._payload(topic, payload)
        if data is None:
            return
        now = self.clock.now()
        self._latest[device_id] = (now, data)
        if self.record_readings:
            for key, value in data.items():
                if key != "t" and isinstance(value, (int, float)) and not isinstance(value, bool):
                    self.store.reading(now, device_id, key, value)

    def _payload(self, topic: str, payload: bytes) -> dict | None:
        """A node's JSON object, or None for anything else. A node that sends rubbish must not stop the hub."""
        try:
            data = json.loads(payload)
        except ValueError:
            data = None
        if isinstance(data, dict):
            self._bad_topics.discard(topic)
            return data
        if topic not in self._bad_topics:           # say so once, not on every message
            self._bad_topics.add(topic)
            self.store.event(self.clock.now(), "bad_payload", level="warn", device=topic.split("/")[3], topic=topic)
        return None

    def _on_node_status(self, topic: str, payload: bytes) -> None:
        node = topic.split("/")[2]
        online = payload.decode(errors="replace") == "online"
        if self._node_online.get(node) != online and node in self.site.nodes:
            self.store.event(self.clock.now(), "node_status", node=node, online=online)
        self._node_online[node] = online
        if not online:
            # Commands sent while a node is away are lost, so forget what we asked of it.
            for dev in self.site.devices.values():
                if dev.node == node and dev.id in self._act:
                    self._act[dev.id].commanded_on = False
                    self._act[dev.id].lease_until = None
            self._led_sent = {k: v for k, v in self._led_sent.items() if self.site.devices[k].node != node}

    def _on_ack(self, topic: str, payload: bytes) -> None:
        device_id = topic.split("/")[3]
        if device_id not in self.site.devices:
            return
        ack = self._payload(topic, payload)
        if ack is None:
            return
        now = self.clock.now()
        known = self.store.ack(now, ack.get("id", ""), bool(ack.get("ok")), ack.get("error"))
        if known and not ack.get("ok"):
            self.store.event(now, "command_failed", level="warn", device=device_id, command_id=ack["id"],
                             error=ack.get("error"))

    def _on_hub_cmd(self, topic: str, payload: bytes) -> None:
        """Run an operator command and answer on the reply topic with the same id."""
        now = self.clock.now()
        cmd: dict = {}
        reply: dict = {"id": "", "name": "", "t": now.isoformat(), "ok": False}
        try:
            try:
                cmd = json.loads(payload)
            except ValueError:
                raise ValueError("payload is not JSON") from None
            if not isinstance(cmd, dict):
                cmd = {}
                raise ValueError("payload must be a JSON object")
            reply["id"], reply["name"] = str(cmd.get("id", "")), str(cmd.get("name", ""))
            handler = self._commands.get(reply["name"])
            if handler is None:
                raise ValueError(f"unknown command {cmd.get('name')!r}")
            reply["result"] = handler(cmd)
            reply["ok"] = True
            self.store.event(now, "command", zone=cmd.get("zone"), planting=cmd.get("planting"),
                             command=cmd, by=cmd.get("by"), result=reply["result"])
        except ValueError as err:
            reply["error"] = str(err)
            self.store.event(now, "command_rejected", command=cmd, by=cmd.get("by"), error=str(err))
        self.bus.publish(topics.hub_reply(self.site.id), reply)

    # ------------------------------------------------------------------ operator actions

    def advance_stage(self, planting_id: str) -> str | None:
        """Move a planting to its next stage (and zone, if the stage needs one).

        Returns the new stage id, or None when the planting is finished and its zone freed.
        """
        if planting_id not in self.plantings:
            raise ValueError(f"unknown planting {planting_id!r}")
        state = self.plantings[planting_id]
        if state.zone is None:
            raise ValueError(f"planting {planting_id} is already finished")
        return self._advance(self.site.plantings[planting_id], state, self.clock.now(), by="operator")

    def water_now(self, zone_id: str, volume_ml: float | None = None, loop_id: str | None = None) -> dict:
        """Give one dose now, without waiting for the trigger or the minimum interval.

        The reservoir interlock and the daily cap still apply, the volume cannot exceed the
        recipe's own dose, and the dose counts towards the interval and cap of later
        automatic doses.
        """
        now = self.clock.now()
        self._check_zone(zone_id)
        if zone_id in self.paused:
            raise ValueError(f"zone {zone_id} is paused")
        if self.observing(zone_id):
            raise ValueError(f"zone {zone_id} is in observe mode ({self.observing(zone_id)})")
        planting_id = next((pid for pid, s in self.plantings.items() if s.zone == zone_id), None)
        stage = self.stage_of(planting_id) if planting_id else None
        loops = [lp for lp in (stage["control"] if stage else [])
                 if lp["strategy"] == "dose" and loop_id in (None, lp["id"])]
        if not loops:
            wanted = f"dose loop {loop_id!r}" if loop_id else "dose loop"
            raise ValueError(f"zone {zone_id} has no {wanted} in its current stage")
        loop = loops[0]
        full = float(loop["dose"]["volume_ml"])
        volume = full if volume_ml is None else float(volume_ml)
        if not 0 < volume <= full:
            raise ValueError(f"volume_ml must be above 0 and at most the recipe dose of {full:g} ml")
        dev = self.site.zone_devices(zone_id, role=loop["actuator"])[0]
        act = self._act.setdefault(dev.id, ActuatorState())
        readings, _ = self._readings(zone_id, now)
        if self._reservoir_low(readings):
            raise ValueError("blocked: reservoir_low")
        if self._node_online.get(dev.node) is False:
            raise ValueError(f"blocked: node {dev.node} is offline")
        if act.busy_until is not None and now < act.busy_until:
            raise ValueError("blocked: a dose is already running")
        used, cap = self._dosed_today(zone_id, loop, now), loop.get("limits", {}).get("max_daily_ml")
        if cap is not None and used + volume > cap:
            raise ValueError(f"blocked: max_daily_ml ({used:g} of {cap:g} ml used in the last 24 h)")
        duration = self._dose(zone_id, self.plantings[planting_id], loop, dev, volume, now, by="operator")
        self._trace(zone_id, loop["id"], dev, True, "on", f"operator dose of {volume:g} ml", {"volume_ml": volume}, now)
        return {"device": dev.id, "volume_ml": volume, "duration_s": duration}

    def set_override(self, zone_id: str, quantity: str, duration: str | float, target: float | None = None,
                     min: float | None = None, max: float | None = None) -> dict:
        """Replace parts of one target band of the zone's current stage until the override expires."""
        now = self.clock.now()
        self._check_zone(zone_id)
        planting_id = next((pid for pid, s in self.plantings.items() if s.zone == zone_id), None)
        stage = self.stage_of(planting_id) if planting_id else None
        if not stage or quantity not in stage["targets"]:
            raise ValueError(f"zone {zone_id} has no target for {quantity!r} in its current stage")
        values = {k: float(v) for k, v in (("min", min), ("target", target), ("max", max)) if v is not None}
        if not values:
            raise ValueError("give at least one of target, min, max")
        band = {**stage["targets"][quantity], **values}
        ordered = [band[k] for k in ("min", "target", "max") if k in band]
        if ordered != sorted(ordered):
            raise ValueError(f"override would give an inconsistent band {band}")
        length = seconds(duration)
        if length <= 0:
            raise ValueError("duration must be above 0")
        until = (now + timedelta(seconds=length)).isoformat()
        self.overrides.setdefault(zone_id, {})[quantity] = {"values": values, "until": until}
        self.store.set_setting("overrides", self.overrides)
        return {"quantity": quantity, "band": band, "until": until}

    def clear_override(self, zone_id: str, quantity: str | None = None, reason: str = "operator") -> list[str]:
        self._check_zone(zone_id)
        current = self.overrides.get(zone_id, {})
        cleared = [q for q in list(current) if quantity in (None, q)]
        for q in cleared:
            del current[q]
        if not current:
            self.overrides.pop(zone_id, None)
        if cleared:
            self.store.set_setting("overrides", self.overrides)
            if reason != "operator":
                self.store.event(self.clock.now(), "override_cleared", zone=zone_id, quantities=cleared, reason=reason)
        return cleared

    def pause_zone(self, zone_id: str, duration: str | float | None = None) -> dict:
        """Stop controlling a zone: every actuator off, nothing switched until it is resumed."""
        now = self.clock.now()
        self._check_zone(zone_id)
        until = (now + timedelta(seconds=seconds(duration))).isoformat() if duration is not None else None
        self.paused[zone_id] = until
        self.store.set_setting("paused", self.paused)
        for dev in self.site.zone_devices(zone_id, cls="actuator"):
            act = self._act.setdefault(dev.id, ActuatorState())
            if act.busy_until is not None and now < act.busy_until:     # stop a dose in progress
                self._send(dev, {"name": "off"})
                act.busy_until = None
            self._drive(dev, False, None, {}, now)
        return {"until": until}

    def resume_zone(self, zone_id: str, reason: str = "operator") -> None:
        self._check_zone(zone_id)
        if zone_id not in self.paused:
            raise ValueError(f"zone {zone_id} is not paused")
        del self.paused[zone_id]
        self.store.set_setting("paused", self.paused)
        if reason != "operator":
            self.store.event(self.clock.now(), "zone_resumed", zone=zone_id, reason=reason)

    def actuator_test(self, device_id: str, duration_s: float = TEST_PULSE_DEFAULT) -> dict:
        """Switch one actuator on for a few seconds (a normal leased command) for commissioning."""
        now = self.clock.now()
        dev = self.site.devices.get(device_id)
        if dev is None or dev.cls != "actuator":
            raise ValueError(f"{device_id!r} is not an actuator of this site")
        duration = float(duration_s)
        if not 0 < duration <= TEST_PULSE_MAX:
            raise ValueError(f"duration_s must be above 0 and at most {TEST_PULSE_MAX:g}")
        act = self._act.setdefault(dev.id, ActuatorState())
        if self._node_online.get(dev.node) is False:
            raise ValueError(f"blocked: node {dev.node} is offline")
        if act.commanded_on or (act.busy_until is not None and now < act.busy_until):
            raise ValueError(f"blocked: {device_id} is already on")
        if "actuator.pump" in dev.roles and any(self._reservoir_low(self._readings(z, now)[0])
                                                for z in self.site.zones_of_device(dev.id)):
            raise ValueError("blocked: reservoir_low")
        self._send(dev, {"name": "on", "duration_s": duration}, force=True)
        act.busy_until = now + timedelta(seconds=duration)
        self.store.event(now, "actuator_test", device=dev.id, duration_s=duration)
        return {"device": dev.id, "duration_s": duration}

    # -- commissioning and observe mode

    def untested(self, zone_id: str) -> list[str]:
        """Real actuators of the zone that have not passed a bench test. Simulated parts need none."""
        return [d.id for d in self.site.zone_devices(zone_id, cls="actuator")
                if self._runtime.get(d.node) != "sim"
                and not self.commissioning.get(("device", d.id, "bench"), {}).get("ok")]

    def observing(self, zone_id: str) -> str | None:
        """Why the zone is in observe mode (decisions are computed and logged, nothing is switched), or None."""
        if self.headless:
            return None
        if self._observing is None:
            self._observing = {}
            for zone in self.site.zones:
                missing = self.untested(zone)
                self._observing[zone] = ("set by operator" if zone in self.observe
                                         else f"not bench-tested: {', '.join(missing)}" if missing else None)
        return self._observing[zone_id]

    def set_zone_mode(self, zone_id: str, mode: str) -> dict:
        self._check_zone(zone_id)
        if mode not in ("observe", "active"):
            raise ValueError("mode must be observe or active")
        if mode == "observe":
            now = self.clock.now()
            for dev in self.site.zone_devices(zone_id, cls="actuator"):     # really off before we stop sending
                act = self._act.setdefault(dev.id, ActuatorState())
                if act.commanded_on or (act.busy_until is not None and now < act.busy_until):
                    self._send(dev, {"name": "off"})
            self.observe.add(zone_id)
            self._observing = None
        else:
            missing = self.untested(zone_id)
            if missing:
                raise ValueError(f"zone {zone_id} stays in observe until these pass a bench test: {', '.join(missing)}")
            self.observe.discard(zone_id)
            self._observing = None
        self.store.set_setting("observe", sorted(self.observe))
        return {"mode": "observe" if self.observing(zone_id) else "active"}

    def commission(self, scope: str, subject: str, step: str, ok: bool, by: str | None = None, data: dict | None = None) -> dict:
        """Record the result of a bench test, calibration or acceptance run."""
        if scope not in COMMISSION_SCOPES or step not in COMMISSION_STEPS:
            raise ValueError(f"scope must be one of {', '.join(COMMISSION_SCOPES)} and step one of {', '.join(COMMISSION_STEPS)}")
        known = {"device": self.site.devices, "node": self.site.nodes, "zone": self.site.zones}[scope]
        if subject not in known:
            raise ValueError(f"unknown {scope} {subject!r}")
        now = self.clock.now()
        self.store.commission(now, scope, subject, step, ok, by, data or {})
        self._observing = None
        self.commissioning[(scope, subject, step)] = {"t": now, "scope": scope, "subject": subject, "step": step,
                                                      "ok": ok, "by": by, "data": data or {}}
        return {"scope": scope, "subject": subject, "step": step, "ok": ok}

    def _cmd_set_zone_mode(self, cmd: dict):
        return self.set_zone_mode(self._arg(cmd, "zone"), self._arg(cmd, "mode"))

    def _cmd_commission(self, cmd: dict):
        data = cmd.get("data", {})
        if not isinstance(data, dict) or not isinstance(cmd.get("ok"), bool):
            raise ValueError("ok must be true or false and data an object")
        return self.commission(self._arg(cmd, "scope"), self._arg(cmd, "subject"), self._arg(cmd, "step"),
                               cmd["ok"], cmd.get("by"), data)

    def _check_zone(self, zone_id: str) -> None:
        if zone_id not in self.site.zones:
            raise ValueError(f"unknown zone {zone_id!r}")

    @staticmethod
    def _arg(cmd: dict, key: str, kind=str, required: bool = True):
        value = cmd.get(key)
        if value is None:
            if required:
                raise ValueError(f"{key} is required")
            return None
        if kind is float:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{key} must be a number")
            return float(value)
        if not isinstance(value, kind):
            raise ValueError(f"{key} must be a {'string' if kind is str else kind.__name__}")
        return value

    def _cmd_advance_stage(self, cmd: dict):
        return {"stage": self.advance_stage(self._arg(cmd, "planting"))}

    def _cmd_water_now(self, cmd: dict):
        return self.water_now(self._arg(cmd, "zone"), self._arg(cmd, "volume_ml", float, required=False),
                              self._arg(cmd, "loop", required=False))

    def _cmd_set_override(self, cmd: dict):
        return self.set_override(self._arg(cmd, "zone"), self._arg(cmd, "quantity"), self._arg(cmd, "duration"),
                                 **{k: self._arg(cmd, k, float, required=False) for k in ("target", "min", "max")})

    def _cmd_clear_override(self, cmd: dict):
        return {"cleared": self.clear_override(self._arg(cmd, "zone"), self._arg(cmd, "quantity", required=False))}

    def _cmd_pause_zone(self, cmd: dict):
        return self.pause_zone(self._arg(cmd, "zone"), self._arg(cmd, "duration", required=False))

    def _cmd_resume_zone(self, cmd: dict):
        return self.resume_zone(self._arg(cmd, "zone"))

    def _cmd_actuator_test(self, cmd: dict):
        duration = self._arg(cmd, "duration_s", float, required=False)
        return self.actuator_test(self._arg(cmd, "device"), TEST_PULSE_DEFAULT if duration is None else duration)

    # ------------------------------------------------------------------ tick

    def tick(self) -> None:
        began = time.perf_counter()
        now = self.clock.now()
        self._expire(now)
        for planting in self.site.plantings.values():
            self._progress(planting, self.plantings[planting.id], now)
        occupants = {s.zone: pid for pid, s in self.plantings.items() if s.zone}
        observed = {z for z in self.site.zones if self.observing(z)}
        for zone_id in self._observed_last - observed:      # back to active: forget what we pretended to send
            for dev in self.site.zone_devices(zone_id, cls="actuator"):
                self._act.pop(dev.id, None)
        self._observed_last = observed
        for zone_id in self.site.zones:
            if self._zones is None or zone_id in self._zones:
                self._run_zone(zone_id, occupants.get(zone_id), now)
        if not self.headless:
            self._render_leds(now)
        if self._retained_at is None or (now - self._retained_at).total_seconds() >= RETAIN_EVERY:
            self.store.retain(now, **self.site.retention)
            self._retained_at = now
        self.tick_ms = (time.perf_counter() - began) * 1000
        if not self.headless:
            self._publish_state(now)

    def _expire(self, now: datetime) -> None:
        """Lift pauses and overrides whose time is up."""
        for zone_id, until in list(self.paused.items()):
            if until is not None and now >= datetime.fromisoformat(until):
                self.resume_zone(zone_id, reason="expired")
        for zone_id, by_quantity in list(self.overrides.items()):
            done = [q for q, o in by_quantity.items() if now >= datetime.fromisoformat(o["until"])]
            for quantity in done:
                self.clear_override(zone_id, quantity, reason="expired")

    def state(self, now: datetime) -> dict:
        """Everything a dashboard needs to start without replaying history."""
        plantings = {}
        for pid, st in self.plantings.items():
            stage = self.stage_of(pid)
            plantings[pid] = {"zone": st.zone, "recipe": self.site.plantings[pid].recipe["id"],
                              "stage": stage["id"] if stage else None, "stage_index": st.stage_index,
                              "stage_started_at": st.stage_started_at.isoformat(), "ready": st.ready}
        actuators = {d.id: self._act.get(d.id, ActuatorState()).dump(now)
                     for d in self.site.devices.values() if d.cls == "actuator"}
        return {"t": now.isoformat(), "version": VERSION, "started_at": self.started_at.isoformat(),
                "tick_ms": round(self.tick_ms, 2), "plantings": plantings, "actuators": actuators,
                "paused": dict(self.paused),
                "observing": {z: why for z in self.site.zones if (why := self.observing(z))},
                "commissioning": [{**r, "t": r["t"].isoformat()} for r in self.commissioning.values()],
                "overrides": {z: {q: {**o["values"], "until": o["until"]} for q, o in by_q.items()}
                              for z, by_q in self.overrides.items()}}

    def _publish_state(self, now: datetime) -> None:
        state = self.state(now)
        signature = json.dumps({k: v for k, v in state.items() if k not in ("t", "tick_ms")}, sort_keys=True)
        sent = self._state_sent
        if sent is None or sent[0] != signature or (now - sent[1]).total_seconds() >= STATUS_REPUBLISH:
            self.bus.publish(topics.hub_state(self.site.id), state, retain=True)
            self._state_sent = (signature, now)

    # ------------------------------------------------------------------ stages

    def stage_of(self, planting_id: str) -> dict | None:
        state = self.plantings[planting_id]
        if state.zone is None:
            return None
        return self.site.plantings[planting_id].recipe["stages"][state.stage_index]

    def _progress(self, planting: Planting, state: PlantingState, now: datetime) -> None:
        if state.zone is None:
            return
        stage = planting.recipe["stages"][state.stage_index]
        advance = stage.get("advance")
        if not advance:
            return  # steady recipes never advance
        elapsed = (now - state.stage_started_at).total_seconds()
        due = elapsed >= seconds(stage.get("duration", {}).get("typical"), default=0)
        if advance["mode"] == "manual":
            state.ready = due
        elif advance["mode"] == "elapsed" and due:
            self._advance(planting, state, now, by="elapsed")
        elif advance["mode"] == "condition":
            readings, _ = self._readings(state.zone, now)
            if self._condition(("advance", planting.id), advance["when"], readings, now):
                self._advance(planting, state, now, by="condition")

    def _advance(self, planting: Planting, state: PlantingState, now: datetime, by: str) -> str | None:
        stages = planting.recipe["stages"]
        old_zone, old_stage = state.zone, stages[state.stage_index]["id"]
        if state.stage_index + 1 >= len(stages):
            self.clear_override(old_zone, reason="planting_finished")
            state.zone, state.ready = None, False
            self.store.save_planting(planting.id, state.dump())
            self.store.event(now, "planting_finished", zone=old_zone, planting=planting.id, by=by)
            return None
        nxt = stages[state.stage_index + 1]
        new_zone = old_zone
        role = nxt.get("zone_role")
        if role and self.site.zones[old_zone].role != role:
            if by != "operator":
                state.ready = True      # a person has to carry it to the other zone first
                return old_stage
            taken = {s.zone for s in self.plantings.values() if s.zone}
            free = [z.id for z in self.site.zones.values() if z.role == role and z.id not in taken]
            if not free:
                raise ValueError(f"no free zone with role {role!r} for stage {nxt['id']}")
            new_zone = free[0]
        self.clear_override(old_zone, reason="stage_advanced")     # the next stage has its own targets
        state.stage_index += 1
        state.stage_started_at, state.zone, state.ready = now, new_zone, False
        self._debounce = {k: v for k, v in self._debounce.items() if k[1] != planting.id}
        self.store.save_planting(planting.id, state.dump())
        self.store.event(now, "stage_advanced", zone=new_zone, planting=planting.id, by=by,
                         from_stage=old_stage, to_stage=nxt["id"], from_zone=old_zone)
        return nxt["id"]

    # ------------------------------------------------------------------ readings and conditions

    def _readings(self, zone_id: str, now: datetime) -> tuple[dict[str, float], set[str]]:
        """Fresh values per quantity for a zone, and the quantities whose sensors have gone quiet."""
        stale_after = self.site.safety["sensor_stale_after"]
        values: dict[str, float] = {}
        stale: set[str] = set()
        for dev in self.site.zone_devices(zone_id, cls="sensor"):
            expected = [q for role in dev.roles for q in self._role_quantities.get(role, [])]
            seen = self._latest.get(dev.id)
            fresh = seen is not None and (now - seen[0]).total_seconds() <= stale_after
            in_grace = seen is None and (now - self.started_at).total_seconds() <= stale_after
            for quantity in expected:
                if fresh and isinstance(seen[1].get(quantity), (int, float)):
                    values[quantity] = seen[1][quantity]
                elif not in_grace:
                    stale.add(quantity)
        return values, stale - set(values)

    def _held(self, key: tuple, met: bool, now: datetime, hold_on: float, hold_off: float) -> bool:
        """Debounce in both directions.

        Turns true once `met` has held for hold_on seconds, and false again only after it
        has been unmet for hold_off seconds. While waiting to turn true, gaps shorter than
        DEBOUNCE_GAP are ignored, so sensor noise around a threshold does not restart the
        wait, but separate brief dips do not add up to a violation either.
        """
        d = self._debounce.setdefault(key, {"on": False, "met_since": None, "unmet_since": None})
        if met:
            d["unmet_since"] = None
            d["met_since"] = d["met_since"] or now
            if (now - d["met_since"]).total_seconds() >= hold_on:
                d["on"] = True
        else:
            d["unmet_since"] = d["unmet_since"] or now
            unmet_for = (now - d["unmet_since"]).total_seconds()
            if unmet_for >= (hold_off if d["on"] else min(hold_off, DEBOUNCE_GAP)):
                d["on"], d["met_since"] = False, None
        return d["on"]

    def _condition(self, key: tuple, cond: dict, readings: dict, now: datetime) -> bool:
        """below/above test that must optionally hold for cond['for']."""
        value = readings.get(cond["quantity"])
        met = value is not None and (("below" in cond and value < cond["below"]) or
                                     ("above" in cond and value > cond["above"]))
        return self._held(key, met, now, seconds(cond.get("for"), default=0), self.site.safety["status_hold"])

    # ------------------------------------------------------------------ zone control

    def _run_zone(self, zone_id: str, planting_id: str | None, now: datetime) -> None:
        readings, stale = self._readings(zone_id, now)
        actuators = {d.id: d for d in self.site.zone_devices(zone_id, cls="actuator")}
        offline = any(self._node_online.get(d.node) is False
                      for d in self.site.zone_devices(zone_id) if d.cls != "indicator")
        reservoir_low = self._reservoir_low(readings)
        paused = zone_id in self.paused
        active: set[str] = set()
        if offline:
            active.add("offline")
        if paused:
            active.add("paused")
        if self.observing(zone_id):
            active.add("observing")

        stage = self._with_overrides(zone_id, self.stage_of(planting_id)) if planting_id else None
        handled: set[str] = set()
        if stage:
            state = self.plantings[planting_id]
            for loop in stage["control"]:
                for dev in self.site.zone_devices(zone_id, role=loop["actuator"]):
                    if paused:      # left unhandled, so it is held off below
                        self._trace(zone_id, loop["id"], dev, False, "off", "paused", {}, now)
                        continue
                    handled.add(dev.id)
                    self._run_loop(zone_id, state, stage, loop, dev, readings, reservoir_low, now)
            active |= self._target_statuses(zone_id, stage, readings, stale, now)
            if reservoir_low and any(l["strategy"] == "dose" for l in stage["control"]):
                active.add("reservoir_low")
            if state.ready:
                active.add("stage_ready")
        for dev_id, dev in actuators.items():
            if dev_id not in handled:   # nothing in this stage uses it: keep it off
                self._drive(dev, False, None, {}, now)

        if not stage:
            top = "offline" if offline else "paused" if paused else "idle"
        else:
            top = self._top_status(active)
        status = {"t": now.isoformat(), "state": top, "active": sorted(active),
                  "planting": planting_id, "stage": stage["id"] if stage else None,
                  "readings": {k: round(v, 2) for k, v in sorted(readings.items())}}
        previous = self.zone_status.get(zone_id)
        self.zone_status[zone_id] = status
        if previous is None or previous["state"] != top:
            self.store.event(now, "status_changed", zone=zone_id, planting=planting_id,
                             state=top, active=sorted(active), was=previous["state"] if previous else None)
        signature = json.dumps([top, sorted(active), status["stage"], planting_id])
        sent = self._status_sent.get(zone_id)
        if self.headless:
            return
        if sent is None or sent[0] != signature or (now - sent[1]).total_seconds() >= STATUS_REPUBLISH:
            self.bus.publish(topics.zone_status(self.site.id, zone_id), status, retain=True)
            self._status_sent[zone_id] = (signature, now)

    def _reservoir_low(self, readings: dict) -> bool:
        level = readings.get("water_level")
        return level is not None and level < self.site.safety["reservoir_min_percent"]

    def _with_overrides(self, zone_id: str, stage: dict | None) -> dict | None:
        """The stage with any active operator overrides merged into its target bands."""
        overrides = self.overrides.get(zone_id)
        if not stage or not overrides:
            return stage
        targets = {q: {**band, **overrides[q]["values"]} if q in overrides else band
                   for q, band in stage["targets"].items()}
        return {**stage, "targets": targets}

    def _trace(self, zone_id: str, loop_id: str, dev: Device, want: bool, action: str, reason: str,
               inputs: dict, now: datetime) -> None:
        """Record why a loop is doing what it is doing.

        A row is stored only when the decision changes (want, action or reason) or what it
        is measured against does (a target, say, after an override). Reasons must not contain
        values that move every tick; the reading goes in `inputs["value"]`, which is ignored
        when looking for a change.
        """
        key = (zone_id, loop_id, dev.id)
        last = self.decisions.get(key)
        if self.observing(zone_id):
            inputs = {**inputs, "observed": True}       # computed, not carried out

        def fixed(values: dict) -> dict:
            return {k: v for k, v in values.items() if k != "value"}

        changed = (last is None or (last["want"], last["action"], last["reason"]) != (want, action, reason)
                   or fixed(last["inputs"]) != fixed(inputs))
        self.decisions[key] = {"t": last["t"] if last and not changed else now, "want": want, "action": action,
                               "reason": reason, "inputs": inputs}
        if changed:
            self.store.decision(now, zone_id, loop_id, dev.id, want, action, reason, inputs)

    def _hhmm(self, t: datetime, now: datetime) -> str:
        local = t.astimezone(self._tz)
        return local.strftime("%H:%M" if local.date() == now.astimezone(self._tz).date() else "%Y-%m-%d %H:%M")

    def _target_statuses(self, zone_id: str, stage: dict, readings: dict, stale: set, now: datetime) -> set[str]:
        hold = self.site.safety["status_hold"]
        raw: set[str] = set()
        result: set[str] = set()
        needed = set(stage["targets"]) | {l["quantity"] for l in stage["control"] if "quantity" in l} \
            | {l["trigger"]["quantity"] for l in stage["control"] if "trigger" in l}
        if needed & stale:
            result.add("sensor_stale")
        for quantity, band in stage["targets"].items():
            value = readings.get(quantity)
            if value is None:
                continue
            if "min" in band and value < band["min"]:
                raw.add(LOW_STATUS.get(quantity, f"{quantity}_low"))
            if "max" in band and value > band["max"]:
                raw.add(HIGH_STATUS.get(quantity, f"{quantity}_high"))
        # Debounce band violations so a brief dip (fan burst, door open) or sensor noise
        # at the edge of a band does not flash the strip.
        known = {k[2] for k in self._debounce if k[0] == "status" and k[1] == zone_id}
        for status in raw | known:
            if self._held(("status", zone_id, status), status in raw, now, hold, hold):
                result.add(status)
        for alert in stage["alerts"]:   # alerts are immediate
            value = readings.get(alert["quantity"])
            if value is not None and (("below" in alert and value < alert["below"]) or
                                      ("above" in alert and value > alert["above"])):
                result.add(alert["status"])
        return result

    def _top_status(self, active: set[str]) -> str:
        if not active:
            return "ok"
        for status in self.site.theme["priority"]:
            if status in active:
                return status
        return sorted(active)[0]

    def _run_loop(self, zone_id: str, state: PlantingState, stage: dict, loop: dict, dev: Device,
                  readings: dict, reservoir_low: bool, now: datetime) -> None:
        strategy, key = loop["strategy"], (zone_id, loop["id"])
        limits = loop.get("limits", {})
        if strategy == "dose":
            self._run_dose(zone_id, state, loop, dev, readings, reservoir_low, now)
            return
        if strategy == "hysteresis":
            quantity = loop["quantity"]
            value = readings.get(quantity)
            target, band = stage["targets"][quantity]["target"], loop.get("band", 1)
            inputs = {"quantity": quantity, "value": value, "target": target, "band": band}
            was = self._latch.get(key, False)
            if value is None:
                self._latch[key] = False        # fail safe: no trusted reading, no actuation
            elif loop["direction"] == "raise":
                if value <= target - band:
                    self._latch[key] = True
                elif value >= target:
                    self._latch[key] = False
            else:
                if value >= target + band:
                    self._latch[key] = True
                elif value <= target:
                    self._latch[key] = False
            want = self._latch.get(key, False)
            last = self.decisions.get((zone_id, loop["id"], dev.id))
            if value is None:
                why = "fail-safe: reading stale"
            elif want != was:
                side = "below" if loop["direction"] == "raise" else "above"
                why = f"want on: {quantity} {side} target band" if want else f"want off: {quantity} reached target"
            elif last and last["want"] == want and last["inputs"].get("why", "").startswith("want"):
                why = last["inputs"]["why"]     # still for the reason that switched it
            else:
                why = f"want {'on' if want else 'off'}: {quantity} inside target band"
        elif strategy == "duty_cycle":
            phase = (now - state.stage_started_at).total_seconds() % seconds(loop["every"])
            want = phase < seconds(loop["on_for"])
            inputs = {"on_for": loop["on_for"], "every": loop["every"]}
            why = f"want {'on' if want else 'off'}: duty cycle {loop['on_for']} every {loop['every']}"
            extra = loop.get("also_when")
            if extra:
                value = readings.get(extra["quantity"])
                inputs.update(quantity=extra["quantity"], value=value, above=extra["above"])
                if value is None:
                    self._latch[key] = False
                elif value > extra["above"]:
                    self._latch[key] = True
                elif value < extra.get("until_below", extra["above"]):
                    self._latch[key] = False
                if not want and self._latch.get(key, False):
                    want, why = True, f"want on: {extra['quantity']} above {extra['above']:g}"
        else:  # schedule
            local = now.astimezone(self._tz)
            start_h, start_m = (int(x) for x in loop["on_at"].split(":"))
            minutes = (local.hour * 60 + local.minute - (start_h * 60 + start_m)) % 1440
            want = minutes < loop["hours"] * 60
            inputs = {"on_at": loop["on_at"], "hours": loop["hours"]}
            why = f"want {'on' if want else 'off'}: schedule {loop['on_at']} for {loop['hours']:g} h"
        blocked = self._drive(dev, want, loop.get("level"), limits, now)
        act = self._act[dev.id]
        self._trace(zone_id, loop["id"], dev, want, "on" if act.commanded_on else "off", blocked or why,
                    {**inputs, "why": why}, now)

    def _doses(self, zone_id: str, loop: dict, since: datetime) -> list[dict]:
        """Doses of this loop: real ones for an active zone, the pretended ones for an observing zone."""
        observed = self.observing(zone_id) is not None
        return [e for e in self.store.events("dose", zone=zone_id, since=since)
                if e["loop"] == loop["id"] and bool(e.get("observed")) == observed]

    def _dosed_today(self, zone_id: str, loop: dict, now: datetime) -> float:
        return sum(e["volume_ml"] for e in self._doses(zone_id, loop, now - timedelta(hours=24)))

    def _dose(self, zone_id: str, state: PlantingState, loop: dict, dev: Device, volume: float, now: datetime,
              by: str) -> float:
        act = self._act.setdefault(dev.id, ActuatorState())
        duration = round(volume / dev.raw["flow_ml_per_s"], 1)
        self._send(dev, {"name": "on", "duration_s": duration})
        act.busy_until = now + timedelta(seconds=duration)
        self._debounce.pop(("dose", state.id, loop["id"]), None)
        extra = {"observed": True} if self.observing(zone_id) else {}
        self.store.event(now, "dose", zone=zone_id, planting=state.id, loop=loop["id"],
                         device=dev.id, volume_ml=volume, duration_s=duration, by=by, **extra)
        return duration

    def _run_dose(self, zone_id: str, state: PlantingState, loop: dict, dev: Device, readings: dict,
                  reservoir_low: bool, now: datetime) -> None:
        act = self._act.setdefault(dev.id, ActuatorState())
        trigger = loop["trigger"]
        inputs = {"quantity": trigger["quantity"], "value": readings.get(trigger["quantity"]),
                  **{k: trigger[k] for k in ("below", "above", "for") if k in trigger}}

        def trace(want: bool, action: str, reason: str) -> None:
            self._trace(zone_id, loop["id"], dev, want, action, reason, inputs, now)

        running = act.busy_until is not None and now < act.busy_until
        if reservoir_low:
            if running:     # stop a dose in progress rather than run the pump dry
                self._send(dev, {"name": "off"})
                act.busy_until = None
                self.store.event(now, "interlock", zone=zone_id, loop=loop["id"], reason="reservoir_low", stopped=True)
            self._debounce.pop(("dose", state.id, loop["id"]), None)
            return trace(False, "off", "blocked: reservoir_low")
        if running:
            return trace(True, "on", "dose running")
        if self._node_online.get(dev.node) is False:
            return trace(False, "off", f"blocked: node {dev.node} offline")
        if not self._condition(("dose", state.id, loop["id"]), trigger, readings, now):
            if inputs["value"] is None:
                return trace(False, "off", "fail-safe: reading stale")
            return trace(False, "off", "want off: trigger not met" + (f" for {trigger['for']}" if "for" in trigger else ""))
        limits = loop.get("limits", {})
        volume = float(loop["dose"]["volume_ml"])
        interval = seconds(limits["min_interval"])
        recent = self._doses(zone_id, loop, now - timedelta(seconds=interval))
        if recent:
            until = recent[-1]["t"] + timedelta(seconds=interval)
            return trace(True, "off", f"blocked: min_interval until {self._hhmm(until, now)}")
        cap = limits.get("max_daily_ml")
        if cap is not None and self._dosed_today(zone_id, loop, now) + volume > cap:
            return trace(True, "off", "blocked: max_daily_ml")
        self._dose(zone_id, state, loop, dev, volume, now, by="trigger")
        return trace(True, "on", f"dosed {volume:g} ml")

    # ------------------------------------------------------------------ actuator driving

    def _reported_on(self, dev: Device) -> bool | None:
        seen = self._latest.get(dev.id)
        return seen[1].get("on") if seen else None

    def _drive(self, dev: Device, want_on: bool, level: float | None, limits: dict, now: datetime) -> str | None:
        """Hold a switched actuator on or off, applying max_on / min_off and renewing its lease.

        Returns the reason when it could not do what was asked, otherwise None.
        """
        act = self._act.setdefault(dev.id, ActuatorState())
        if self._node_online.get(dev.node) is False:
            return f"blocked: node {dev.node} offline"
        if act.busy_until is not None:      # a dose or test pulse owns this device
            if now < act.busy_until:
                return "blocked: dose or test pulse running"
            act.busy_until = None
        lease = self.site.safety["actuator_lease"]
        min_off = seconds(limits.get("min_off"), default=DEFAULT_MIN_OFF)
        blocked = None
        if want_on:
            max_on = limits.get("max_on")
            if act.commanded_on and max_on and (now - act.on_since).total_seconds() >= seconds(max_on):
                act.locked_until = now + timedelta(seconds=min_off)
                pretend = {"observed": True} if any(self.observing(z) for z in self.site.zones_of_device(dev.id)) else {}
                self.store.event(now, "limit", device=dev.id, reason="max_on", **pretend)
                blocked = f"blocked: max_on, off until {self._hhmm(act.locked_until, now)}"
            elif act.locked_until and now < act.locked_until:
                blocked = f"blocked: max_on, off until {self._hhmm(act.locked_until, now)}"
            elif not act.commanded_on and act.off_since and (now - act.off_since).total_seconds() < min_off:
                blocked = f"blocked: min_off until {self._hhmm(act.off_since + timedelta(seconds=min_off), now)}"
            want_on = blocked is None
        if want_on:
            renew = act.lease_until is None or (act.lease_until - now).total_seconds() < lease / 2
            if not act.commanded_on or renew or act.level != level:
                cmd = {"name": "on", "duration_s": lease}
                if level is not None:
                    cmd["level"] = level
                self._send(dev, cmd)
                if not act.commanded_on:
                    act.on_since = now
                act.commanded_on, act.level, act.lease_until = True, level, now + timedelta(seconds=lease)
        elif act.commanded_on or self._reported_on(dev):
            self._send(dev, {"name": "off"})
            if act.commanded_on:
                act.off_since = now
            act.commanded_on, act.on_since, act.lease_until = False, None, None
        return blocked

    def _send(self, dev: Device, cmd: dict, force: bool = False) -> None:
        """force: send even to an actuator of an observing zone (test pulses)."""
        if not force and dev.cls == "actuator" and any(self.observing(z) for z in self.site.zones_of_device(dev.id)):
            return
        cmd = {"id": uuid.uuid4().hex[:12], **cmd}
        self.store.command(self.clock.now(), cmd["id"], dev.id, cmd["name"],
                           {k: v for k, v in cmd.items() if k not in ("id", "name")})
        self.bus.publish(topics.device(self.site.id, dev.node, dev.id, "cmd"), cmd)

    # ------------------------------------------------------------------ LEDs

    def _render_leds(self, now: datetime) -> None:
        theme = self.site.theme
        hour = now.astimezone(self._tz).hour
        start, end = theme["brightness"]["night_hours"]
        night = (start <= hour or hour < end) if start > end else (start <= hour < end)
        brightness = theme["brightness"]["night" if night else "day"]
        strips: dict[str, list[dict]] = {}
        for zone in self.site.zones.values():
            if not zone.indicator:
                continue
            status = self.zone_status[zone.id]["state"]
            style = theme["statuses"].get(status) or theme["statuses"]["critical"]
            strip = self.site.devices[zone.indicator["strip"]]
            color = list(style["color"])
            if strip.model.get("channels") == "rgb":    # no white LED: mix W into RGB
                white = color[3]
                color = [min(255, c + white) for c in color[:3]] + [0]
            strips.setdefault(strip.id, []).append({"zone": zone.id, "leds": zone.indicator["leds"],
                                                    "status": status, "color": color, "effect": style["effect"]})
        for strip_id, segments in strips.items():
            strip = self.site.devices[strip_id]
            if self._node_online.get(strip.node) is False:
                continue
            body = {"name": "render", "brightness": brightness, "segments": segments}
            signature = json.dumps(body, sort_keys=True)
            if self._led_sent.get(strip_id) != signature:
                self._send(strip, body)
                self._led_sent[strip_id] = signature


def _zone(name: str):
    from zoneinfo import ZoneInfo
    return ZoneInfo(name)


def _version() -> str:
    from importlib.metadata import PackageNotFoundError, version
    try:
        return version("fullstack-food")
    except PackageNotFoundError:
        return "unknown"


VERSION = _version()
