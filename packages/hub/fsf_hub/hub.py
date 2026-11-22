"""The hub: reads device state from the bus, runs each zone's recipe stage, drives
actuators within safety limits, and publishes zone status and LED renders.

The hub is driven by tick(): call it every 30 s or so with any Clock. It keeps no
threads of its own, which is what lets tests run it against a virtual clock.
"""

from __future__ import annotations

import json
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
    busy_until: datetime | None = None      # a timed dose is running


class Hub:
    def __init__(self, site: Site, catalog: Catalog, bus, clock, store: Store | None = None,
                 record_readings: bool = True):
        self.site, self.bus, self.clock = site, bus, clock
        self.store = store or Store()
        self.record_readings = record_readings
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
        sid = self.site.id
        self.bus.subscribe(f"{topics.ROOT}/{sid}/+/+/state", self._on_state)
        self.bus.subscribe(f"{topics.ROOT}/{sid}/+/status", self._on_node_status)
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
        data = json.loads(payload)
        now = self.clock.now()
        self._latest[device_id] = (now, data)
        if self.record_readings:
            for key, value in data.items():
                if key != "t" and isinstance(value, (int, float)) and not isinstance(value, bool):
                    self.store.reading(now, device_id, key, value)

    def _on_node_status(self, topic: str, payload: bytes) -> None:
        node = topic.split("/")[2]
        online = payload.decode() == "online"
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

    def _on_hub_cmd(self, topic: str, payload: bytes) -> None:
        cmd = json.loads(payload)
        if cmd.get("name") == "advance_stage":
            try:
                self.advance_stage(cmd["planting"])
            except (KeyError, ValueError) as err:
                self.store.event(self.clock.now(), "command_rejected", command=cmd, error=str(err))

    # ------------------------------------------------------------------ operator actions

    def advance_stage(self, planting_id: str) -> str | None:
        """Move a planting to its next stage (and zone, if the stage needs one).

        Returns the new stage id, or None when the planting is finished and its zone freed.
        """
        state = self.plantings[planting_id]
        if state.zone is None:
            raise ValueError(f"planting {planting_id} is already finished")
        return self._advance(self.site.plantings[planting_id], state, self.clock.now(), by="operator")

    # ------------------------------------------------------------------ tick

    def tick(self) -> None:
        now = self.clock.now()
        for planting in self.site.plantings.values():
            self._progress(planting, self.plantings[planting.id], now)
        occupants = {s.zone: pid for pid, s in self.plantings.items() if s.zone}
        for zone_id in self.site.zones:
            self._run_zone(zone_id, occupants.get(zone_id), now)
        self._render_leds(now)

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
        level = readings.get("water_level")
        reservoir_low = level is not None and level < self.site.safety["reservoir_min_percent"]
        active: set[str] = set()
        if offline:
            active.add("offline")

        stage = self.stage_of(planting_id) if planting_id else None
        handled: set[str] = set()
        if stage:
            state = self.plantings[planting_id]
            for loop in stage["control"]:
                for dev in self.site.zone_devices(zone_id, role=loop["actuator"]):
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
            top = "offline" if offline else "idle"
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
        if sent is None or sent[0] != signature or (now - sent[1]).total_seconds() >= STATUS_REPUBLISH:
            self.bus.publish(topics.zone_status(self.site.id, zone_id), status, retain=True)
            self._status_sent[zone_id] = (signature, now)

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
            value = readings.get(loop["quantity"])
            target, band = stage["targets"][loop["quantity"]]["target"], loop.get("band", 1)
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
        elif strategy == "duty_cycle":
            phase = (now - state.stage_started_at).total_seconds() % seconds(loop["every"])
            want = phase < seconds(loop["on_for"])
            extra = loop.get("also_when")
            if extra:
                value = readings.get(extra["quantity"])
                if value is None:
                    self._latch[key] = False
                elif value > extra["above"]:
                    self._latch[key] = True
                elif value < extra.get("until_below", extra["above"]):
                    self._latch[key] = False
                want = want or self._latch.get(key, False)
        else:  # schedule
            local = now.astimezone(self._tz)
            start_h, start_m = (int(x) for x in loop["on_at"].split(":"))
            minutes = (local.hour * 60 + local.minute - (start_h * 60 + start_m)) % 1440
            want = minutes < loop["hours"] * 60
        self._drive(dev, want, loop.get("level"), limits, now)

    def _run_dose(self, zone_id: str, state: PlantingState, loop: dict, dev: Device, readings: dict,
                  reservoir_low: bool, now: datetime) -> None:
        act = self._act.setdefault(dev.id, ActuatorState())
        running = act.busy_until is not None and now < act.busy_until
        if reservoir_low:
            if running:     # stop a dose in progress rather than run the pump dry
                self._send(dev, {"name": "off"})
                act.busy_until = None
                self.store.event(now, "interlock", zone=zone_id, loop=loop["id"], reason="reservoir_low", stopped=True)
            self._debounce.pop(("dose", state.id, loop["id"]), None)
            return
        if running or self._node_online.get(dev.node) is False:
            return
        if not self._condition(("dose", state.id, loop["id"]), loop["trigger"], readings, now):
            return
        limits = loop.get("limits", {})
        volume = float(loop["dose"]["volume_ml"])
        doses = [e for e in self.store.events("dose", zone=zone_id, since=now - timedelta(hours=24))
                 if e["loop"] == loop["id"]]
        history = self.store.events("dose", zone=zone_id, since=now - timedelta(seconds=seconds(limits["min_interval"])))
        if any(e["loop"] == loop["id"] for e in history):
            return
        cap = limits.get("max_daily_ml")
        if cap is not None and sum(e["volume_ml"] for e in doses) + volume > cap:
            return
        duration = volume / dev.raw["flow_ml_per_s"]
        self._send(dev, {"name": "on", "duration_s": round(duration, 1)})
        act.busy_until = now + timedelta(seconds=duration)
        self._debounce.pop(("dose", state.id, loop["id"]), None)
        self.store.event(now, "dose", zone=zone_id, planting=state.id, loop=loop["id"],
                         device=dev.id, volume_ml=volume, duration_s=round(duration, 1))

    # ------------------------------------------------------------------ actuator driving

    def _reported_on(self, dev: Device) -> bool | None:
        seen = self._latest.get(dev.id)
        return seen[1].get("on") if seen else None

    def _drive(self, dev: Device, want_on: bool, level: float | None, limits: dict, now: datetime) -> None:
        """Hold a switched actuator on or off, applying max_on / min_off and renewing its lease."""
        act = self._act.setdefault(dev.id, ActuatorState())
        if self._node_online.get(dev.node) is False:
            return
        if act.busy_until is not None:      # a dose loop owns this device
            if now < act.busy_until:
                return
            act.busy_until = None
        lease = self.site.safety["actuator_lease"]
        min_off = seconds(limits.get("min_off"), default=DEFAULT_MIN_OFF)
        if want_on:
            max_on = limits.get("max_on")
            if act.commanded_on and max_on and (now - act.on_since).total_seconds() >= seconds(max_on):
                act.locked_until = now + timedelta(seconds=min_off)
                self.store.event(now, "limit", device=dev.id, reason="max_on")
                want_on = False
            elif act.locked_until and now < act.locked_until:
                want_on = False
            elif not act.commanded_on and act.off_since and (now - act.off_since).total_seconds() < min_off:
                want_on = False
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

    def _send(self, dev: Device, cmd: dict) -> None:
        cmd = {"id": uuid.uuid4().hex[:12], **cmd}
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
