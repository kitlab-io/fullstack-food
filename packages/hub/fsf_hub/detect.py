"""Fault detection: things that are wrong although every reading is inside its band.

The hub feeds this with what it sends, hears and decides; `zone()` returns the statuses
that are true for a zone right now. Each detection also logs a `detection` event when it
starts and `detection_cleared` when it ends, naming the device and what was seen.

    no_effect        a dose did not raise its quantity, or a heater/humidifier/fan has been
                     wanted on for a long time without moving its quantity
    actuator_fault   an actuator does not acknowledge commands
    sensor_fault     a sensor repeats one value for an implausibly long time, or reports a
                     value no real process could produce (such values are also not used)
    water_mismatch   the reservoir level falls although nothing was dosed
    node_unstable    a node keeps dropping off and coming back

Thresholds are in `detection:` of the site file (defaults in fsf_core.catalog).
"""

from __future__ import annotations

from datetime import datetime, timedelta

# Values outside these cannot be real, whatever the part. A little beyond the scale is
# allowed for noise at the ends.
PHYSICAL = {"air_temperature": (-30.0, 70.0), "soil_temperature": (-30.0, 70.0), "relative_humidity": (-2.0, 102.0),
            "soil_moisture": (-2.0, 102.0), "water_level": (-2.0, 102.0), "co2": (200.0, 50000.0),
            "illuminance": (-1.0, 200000.0)}


def plausible(quantity: str, value: float) -> bool:
    low, high = PHYSICAL.get(quantity, (float("-inf"), float("inf")))
    return low <= value <= high


class Detector:
    def __init__(self, hub):
        self.hub = hub
        self.cfg = hub.site.detection
        self.active: dict[tuple[str, str], dict] = {}           # (status, subject) -> {"since", "zones", "detail"}
        self._pending: dict[str, tuple[str, datetime]] = {}     # command id -> (device, sent at)
        self._doses: dict[tuple[str, str], dict] = {}           # (zone, loop) -> {"t", "before", "best", "quantity", "rising"}
        self._pushing: dict[tuple[str, str, str], dict] = {}    # (zone, loop, device) -> {"t", "value"}
        self._unchanged: dict[tuple[str, str], tuple[float, datetime]] = {}   # (device, quantity) -> (value, since)
        self._levels: dict[str, list[tuple[datetime, float]]] = {}
        self._drops: dict[str, list[datetime]] = {}             # node -> times it went offline

    # ------------------------------------------------------------------ bookkeeping

    def _set(self, status: str, subject: str, on: bool, zones: list[str], now: datetime, detail: str = "") -> None:
        key = (status, subject)
        if on and key not in self.active:
            self.active[key] = {"since": now, "zones": zones, "detail": detail}
            self.hub.store.event(now, "detection", level="warn", zone=zones[0] if zones else None, status=status,
                                 subject=subject, detail=detail)
        elif not on and key in self.active:
            zones = self.active.pop(key)["zones"]
            self.hub.store.event(now, "detection_cleared", zone=zones[0] if zones else None, status=status, subject=subject)

    def _zones_of(self, device_id: str) -> list[str]:
        return self.hub.site.zones_of_device(device_id)

    # ------------------------------------------------------------------ what the hub tells us

    def sent(self, device_id: str, command_id: str, now: datetime) -> None:
        self._pending[command_id] = (device_id, now)

    def acked(self, command_id: str, now: datetime) -> None:
        device_id, _ = self._pending.pop(command_id, (None, None))
        if device_id:                                           # it answers again
            for other in [k for k, (dev, _) in self._pending.items() if dev == device_id]:
                del self._pending[other]
            self._set("actuator_fault", device_id, False, [], now)

    def dosed(self, zone_id: str, loop: dict, value: float | None, now: datetime) -> None:
        trigger = loop["trigger"]
        self._doses[(zone_id, loop["id"])] = {"t": now, "before": value, "best": value, "quantity": trigger["quantity"],
                                              "rising": "below" in trigger}

    def node_changed(self, node: str, online: bool, now: datetime) -> None:
        if not online:
            self._drops.setdefault(node, []).append(now)

    def reading(self, device_id: str, quantity: str, value: float, now: datetime) -> None:
        last = self._unchanged.get((device_id, quantity))
        if last is None or last[0] != value:
            self._unchanged[(device_id, quantity)] = (value, now)
        if not plausible(quantity, value):
            self._set("sensor_fault", f"{device_id}/{quantity}/range", True, self._zones_of(device_id), now,
                      f"{device_id} reports {quantity} = {value:g}, which cannot be real")
        else:
            self._set("sensor_fault", f"{device_id}/{quantity}/range", False, [], now)
        if quantity == "water_level":
            self._levels.setdefault(device_id, []).append((now, value))

    # ------------------------------------------------------------------ checks, once per tick

    def tick(self, now: datetime) -> None:
        cfg = self.cfg
        for command_id, (device_id, sent_at) in list(self._pending.items()):
            if (now - sent_at).total_seconds() >= cfg["ack_within"]:
                del self._pending[command_id]
                if self.hub._node_online.get(self.hub.site.devices[device_id].node) is not False:
                    self._set("actuator_fault", device_id, True, self._zones_of(device_id), now,
                              f"{device_id} did not acknowledge a command within {cfg['ack_within']:g} s")
        window = timedelta(seconds=cfg["flap_window"])
        for node, drops in self._drops.items():
            drops[:] = [t for t in drops if now - t <= window]
            zones = sorted({z for d in self.hub.site.devices.values() if d.node == node for z in self._zones_of(d.id)})
            self._set("node_unstable", node, len(drops) >= cfg["flap_count"], zones, now,
                      f"node {node} went offline {len(drops)} times in {cfg['flap_window'] / 60:g} min")
        self._reservoirs(now)

    def _reservoirs(self, now: datetime) -> None:
        """The level falls although no pump drawing from it ran."""
        cfg = self.cfg
        span = timedelta(seconds=cfg["leak_window"])
        for device_id, samples in self._levels.items():
            samples[:] = [(t, v) for t, v in samples if now - t <= span]
            zones = self._zones_of(device_id)
            if len(samples) < 2:
                continue
            since = samples[0][0]
            key = ("water_mismatch", device_id)
            if samples[-1][1] - min(v for _, v in samples) >= cfg["leak_drop"] / 2:    # someone refilled it
                self._levels[device_id] = samples[-1:]
                self._set(*key, False, zones, now)
                continue
            dosed = any(self.hub.store.events("dose", zone=z, since=since - timedelta(minutes=5)) for z in zones)
            fell = samples[0][1] - samples[-1][1]
            if dosed:
                self._levels[device_id] = samples[-1:]          # start again after the dose
                continue
            if fell >= cfg["leak_drop"]:
                self._set(*key, True, zones, now, f"{device_id} fell {fell:.1f} points in "
                          f"{(samples[-1][0] - since).total_seconds() / 3600:.1f} h with no watering")
            elif key in self.active and now - self.active[key]["since"] >= span and fell < cfg["leak_drop"] / 2:
                self._set(*key, False, zones, now)

    def zone(self, zone_id: str, stage: dict | None, readings: dict, observing: bool, now: datetime) -> set[str]:
        """Run the per-zone checks and return the detection statuses active for this zone."""
        cfg = self.cfg
        hub = self.hub
        loops = {lp["id"]: lp for lp in (stage or {}).get("control", [])}

        # -- a dose that changed nothing
        for (zone, loop_id), dose in list(self._doses.items()):
            if zone != zone_id:
                continue
            value = readings.get(dose["quantity"])
            if value is not None and dose["before"] is not None:
                better = value > dose["best"] if dose["rising"] else value < dose["best"]
                if better:
                    dose["best"] = value
            moved = abs((dose["best"] or 0) - (dose["before"] or 0)) if dose["before"] is not None else 0.0
            key = ("no_effect", f"{zone}/{loop_id}")
            if moved >= cfg["dose_min_change"]:
                self._set(*key, False, [zone], now)
                if (now - dose["t"]).total_seconds() >= cfg["dose_effect_within"]:
                    del self._doses[(zone, loop_id)]
            elif (now - dose["t"]).total_seconds() >= cfg["dose_effect_within"] and dose["before"] is not None:
                self._set(*key, True, [zone], now, f"{dose['quantity']} did not change after the last dose "
                          f"({dose['before']:g} before, {dose['best']:g} at best)")

        # -- an actuator wanted on for a long time that moves nothing
        for (zone, loop_id, device_id), decision in hub.decisions.items():
            loop = loops.get(loop_id)
            if zone != zone_id or loop is None or loop["strategy"] != "hysteresis":
                continue
            key, track = ("no_effect", f"{zone}/{loop_id}"), (zone, loop_id, device_id)
            value = readings.get(loop["quantity"])
            pushing = decision["want"] and not observing and value is not None
            if not pushing:
                self._pushing.pop(track, None)
                if not decision["want"]:
                    self._set(*key, False, [zone], now)
                continue
            start = self._pushing.setdefault(track, {"t": now, "value": value})
            progress = (value - start["value"]) * (1 if loop["direction"] == "raise" else -1)
            if progress >= cfg["progress_min"]:
                self._pushing[track] = {"t": now, "value": value}
                self._set(*key, False, [zone], now)
            elif (now - start["t"]).total_seconds() >= cfg["ineffective_after"]:
                self._set(*key, True, [zone], now, f"{device_id} has been wanted on for "
                          f"{cfg['ineffective_after'] / 3600:g} h and {loop['quantity']} went from {start['value']:g} to {value:g}")

        # -- a sensor that repeats itself
        needed = set((stage or {}).get("targets", {})) | {lp["quantity"] for lp in loops.values() if "quantity" in lp} \
            | {lp["trigger"]["quantity"] for lp in loops.values() if "trigger" in lp}
        for dev in hub.site.zone_devices(zone_id, cls="sensor"):
            for quantity in needed:
                seen = self._unchanged.get((dev.id, quantity))
                latest = hub._latest.get(dev.id)
                if seen is None or latest is None:
                    continue
                fresh = (now - latest[0]).total_seconds() <= hub.site.safety["sensor_stale_after"]
                stuck = fresh and (now - seen[1]).total_seconds() >= cfg["stuck_after"]
                self._set("sensor_fault", f"{dev.id}/{quantity}/stuck", stuck, self._zones_of(dev.id), now,
                          f"{dev.id} has reported {quantity} = {seen[0]:g} without any change for {cfg['stuck_after'] / 3600:g} h")

        return {status for (status, _), info in self.active.items() if zone_id in info["zones"]}
