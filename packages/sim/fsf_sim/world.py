"""Simulated nodes and zone physics.

The simulator stands in for every node of a site. It speaks the same MQTT contract a
real node does (state, cmd, ack, status, and switching actuators off when their lease
expires), so the hub cannot tell the difference. Physics are deliberately simple
first-order models: good enough to exercise control logic, not to predict a real room.
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from fsf_core import topics
from fsf_core.catalog import Device, Site

OUTDOOR_CO2 = 420.0
NOISE = {"air_temperature": 0.05, "relative_humidity": 0.3, "soil_moisture": 0.2, "co2": 5.0,
         "water_level": 0.1, "illuminance": 5.0, "soil_temperature": 0.05}
AIR_DEFAULTS = {"loss_per_h": 0.5, "heater_degc_per_h": 6.0, "humidity_loss_per_h": 1.5,
                "humidifier_pct_per_h": 300.0, "fan_exchange_per_h": 4.0, "co2_leak_per_h": 0.2,
                "co2_production_ppm_per_h": 0.0}


@dataclass
class ZoneSim:
    id: str
    enclosure: str                      # open: air follows ambient; chamber: own air volume
    air: dict
    soil: dict | None
    air_temperature: float = 20.0
    relative_humidity: float = 50.0
    co2: float = OUTDOOR_CO2
    soil_moisture: float | None = None
    illuminance: float = 0.0
    occupied: bool = False              # learned from the hub's zone status


@dataclass
class ActuatorSim:
    device: Device
    on_from: datetime | None = None
    on_until: datetime | None = None
    level: float = 1.0
    on_seconds: float = 0.0             # lifetime total, for assertions
    delivered_ml: float = 0.0           # pumps only
    log: list[tuple[datetime, bool]] = field(default_factory=list)

    def is_on(self, now: datetime) -> bool:
        return self.on_from is not None and self.on_until is not None and now < self.on_until


class Sim:
    def __init__(self, site: Site, config: dict, bus, clock, report_interval: float = 60.0):
        self.site, self.bus, self.clock = site, bus, clock
        self.config = config
        self.report_interval = report_interval
        self.rng = random.Random(config.get("seed", 0))
        self.ambient = {"air_temperature": {"mean": 21.0, "daily_amplitude": 0.0}, "relative_humidity": 50.0,
                        **config.get("ambient", {})}
        self.reservoirs = {k: dict(v) for k, v in config.get("reservoirs", {}).items()}
        self.zones: dict[str, ZoneSim] = {}
        for zone in site.zones.values():
            zc = config.get("zones", {}).get(zone.id, {})
            zs = ZoneSim(id=zone.id, enclosure=zc.get("enclosure", "open"),
                         air={**AIR_DEFAULTS, **zc.get("air", {})}, soil=zc.get("soil"))
            zs.air_temperature = zc.get("air", {}).get("initial_temperature", self._ambient_temperature(clock.now()))
            zs.relative_humidity = zc.get("air", {}).get("initial_humidity", self.ambient["relative_humidity"])
            if zs.soil:
                zs.soil_moisture = float(zs.soil["initial"])
            self.zones[zone.id] = zs
        self.actuators = {d.id: ActuatorSim(d) for d in site.devices.values() if d.cls == "actuator"}
        self.leds: dict[str, dict] = {}                 # strip id -> last render command
        self.led_history: dict[str, list[tuple[datetime, dict[str, str]]]] = {}
        self.offline_nodes: set[str] = set()
        self.dropouts: set[str] = set()
        self.stuck: dict[tuple[str, str], float] = {}
        self.no_flow: set[str] = set()
        self._last_report: datetime | None = None

    # ------------------------------------------------------------------ lifecycle

    def start(self) -> None:
        sid = self.site.id
        for node in self.site.nodes:
            self.bus.publish(topics.node_status(sid, node), "online", retain=True)
        self.bus.subscribe(f"{topics.ROOT}/{sid}/+/+/cmd", self._on_cmd)
        self.bus.subscribe(f"{topics.ROOT}/{sid}/zone/+/status", self._on_zone_status)
        now = self.clock.now()
        for act in self.actuators.values():
            self._publish_actuator(act, now)
        self._report(now)

    # ------------------------------------------------------------------ fault injection and scenario controls

    def sensor_dropout(self, device_id: str, active: bool = True) -> None:
        """The sensor stops reporting (broken wire, crashed driver)."""
        (self.dropouts.add if active else self.dropouts.discard)(device_id)

    def sensor_stuck(self, device_id: str, quantity: str, value: float | None) -> None:
        """The sensor keeps reporting one value. Pass None to clear."""
        if value is None:
            self.stuck.pop((device_id, quantity), None)
        else:
            self.stuck[(device_id, quantity)] = value

    def node_offline(self, node: str, offline: bool = True) -> None:
        """The node drops off the network. It keeps running locally, so leases still expire."""
        if offline:
            self.offline_nodes.add(node)
            self.bus.publish(topics.node_status(self.site.id, node), "offline", retain=True)   # last will
        else:
            self.offline_nodes.discard(node)
            self.bus.publish(topics.node_status(self.site.id, node), "online", retain=True)
            for act in self.actuators.values():
                if act.device.node == node:
                    self._publish_actuator(act, self.clock.now())

    def pump_no_flow(self, device_id: str, active: bool = True) -> None:
        """The pump runs but moves no water (airlock, kinked tube)."""
        (self.no_flow.add if active else self.no_flow.discard)(device_id)

    def set_reservoir(self, device_id: str, volume_ml: float) -> None:
        self.reservoirs[device_id]["volume_ml"] = volume_ml

    def set_ambient(self, air_temperature: float | None = None, relative_humidity: float | None = None) -> None:
        if air_temperature is not None:
            self.ambient["air_temperature"] = {**self.ambient["air_temperature"], "mean": air_temperature}
        if relative_humidity is not None:
            self.ambient["relative_humidity"] = relative_humidity

    # ------------------------------------------------------------------ commands from the hub

    def _on_cmd(self, topic: str, payload: bytes) -> None:
        _, _, node, device_id, _ = topic.split("/")
        if node in self.offline_nodes or device_id not in self.site.devices:
            return
        cmd = json.loads(payload)
        now = self.clock.now()
        dev = self.site.devices[device_id]
        ok, error = True, None
        if device_id in self.actuators:
            act = self.actuators[device_id]
            if cmd["name"] == "on" and cmd.get("duration_s", 0) > 0:
                if not act.is_on(now):
                    act.on_from = now
                    act.log.append((now, True))
                act.on_until = now + timedelta(seconds=cmd["duration_s"])
                act.level = cmd.get("level", 1.0)
            elif cmd["name"] == "off":
                self._switch_off(act, now)
            else:
                ok, error = False, "actuators accept on (with duration_s) and off"
            self._publish_actuator(act, now)
        elif "indicator.led_strip" in dev.roles and cmd["name"] == "render":
            self.leds[device_id] = cmd
            self.led_history.setdefault(device_id, []).append((now, {s["zone"]: s["status"] for s in cmd["segments"]}))
            self.bus.publish(topics.device(self.site.id, node, device_id, "state"),
                             {"t": now.isoformat(), "brightness": cmd["brightness"], "segments": cmd["segments"]}, retain=True)
        else:
            ok, error = False, f"unsupported command {cmd.get('name')!r}"
        ack = {"id": cmd.get("id", ""), "ok": ok}
        if error:
            ack["error"] = error
        self.bus.publish(topics.device(self.site.id, node, device_id, "ack"), ack)

    def _on_zone_status(self, topic: str, payload: bytes) -> None:
        zone_id = topic.split("/")[3]
        if zone_id in self.zones:   # substrate only gives off CO2 where a planting actually is
            self.zones[zone_id].occupied = json.loads(payload).get("planting") is not None

    def _switch_off(self, act: ActuatorSim, now: datetime) -> None:
        if act.is_on(now):
            act.log.append((now, False))
        act.on_from = None

    def _publish_actuator(self, act: ActuatorSim, now: datetime) -> None:
        if act.device.node in self.offline_nodes:
            return
        self.bus.publish(topics.device(self.site.id, act.device.node, act.device.id, "state"),
                         {"t": now.isoformat(), "on": act.is_on(now), "level": act.level}, retain=True)

    # ------------------------------------------------------------------ physics

    def _ambient_temperature(self, now: datetime) -> float:
        amb = self.ambient["air_temperature"]
        hour = now.hour + now.minute / 60
        return amb["mean"] + amb.get("daily_amplitude", 0.0) * math.sin(2 * math.pi * (hour - 9) / 24)

    def _on_fraction(self, act: ActuatorSim, start: datetime, end: datetime) -> float:
        if act.on_from is None or act.on_until is None:
            return 0.0
        overlap = (min(act.on_until, end) - max(act.on_from, start)).total_seconds()
        return max(0.0, overlap) / (end - start).total_seconds()

    def step(self, dt: float) -> None:
        """Advance the world by dt seconds, ending at clock.now()."""
        now = self.clock.now()
        start = now - timedelta(seconds=dt)
        hours = dt / 3600.0
        ambient_t = self._ambient_temperature(now)
        ambient_h = self.ambient["relative_humidity"]
        daylight = max(0.0, math.sin(math.pi * (now.hour + now.minute / 60 - 6) / 12)) * 300.0

        for zone in self.zones.values():
            frac = {"heater": 0.0, "humidifier": 0.0, "fan": 0.0, "grow_light": 0.0}
            light_level = 0.0
            pumped_ml = 0.0
            for dev in self.site.zone_devices(zone.id, cls="actuator"):
                act = self.actuators[dev.id]
                f = self._on_fraction(act, start, now)
                act.on_seconds += f * dt
                for role in dev.roles:
                    kind = role.split(".")[1]
                    if kind in frac:
                        frac[kind] = max(frac[kind], f)
                        if kind == "grow_light":
                            light_level = f * act.level
                    elif kind == "pump" and f > 0:
                        pumped_ml += self._pump(zone.id, dev, act, f * dt)

            air = zone.air
            if zone.enclosure == "chamber":
                exchange = frac["fan"] * air["fan_exchange_per_h"]
                zone.air_temperature += ((ambient_t - zone.air_temperature) * (air["loss_per_h"] + exchange)
                                         + frac["heater"] * air["heater_degc_per_h"]) * hours
                zone.relative_humidity += ((ambient_h - zone.relative_humidity) * (air["humidity_loss_per_h"] + exchange)
                                           + frac["humidifier"] * air["humidifier_pct_per_h"]) * hours
                zone.relative_humidity = min(100.0, max(0.0, zone.relative_humidity))
                zone.co2 += ((air["co2_production_ppm_per_h"] if zone.occupied else 0.0)
                             - (zone.co2 - OUTDOOR_CO2) * (air["co2_leak_per_h"] + exchange)) * hours
            else:
                zone.air_temperature, zone.relative_humidity, zone.co2 = ambient_t, ambient_h, OUTDOOR_CO2
            zone.illuminance = daylight + 8000.0 * light_level
            if zone.soil:
                evaporation = (zone.soil["evaporation_pct_per_h"] * (1 + 0.5 * frac["grow_light"])
                               * max(0.2, 1 + 0.03 * (zone.air_temperature - 21)))
                zone.soil_moisture += pumped_ml / zone.soil["ml_per_percent"] - evaporation * hours
                zone.soil_moisture = min(100.0, max(0.0, zone.soil_moisture))

        for act in self.actuators.values():     # the node enforces the lease locally
            if act.on_from is not None and now >= act.on_until:
                act.log.append((act.on_until, False))
                act.on_from = None
                self._publish_actuator(act, now)
        self.bus.publish(topics.clock(self.site.id), {"t": now.isoformat()}, retain=True)
        if self._last_report is None or (now - self._last_report).total_seconds() >= self.report_interval:
            self._report(now)

    def _reservoir_for(self, zone_id: str) -> dict | None:
        for dev in self.site.zone_devices(zone_id, role="sensor.water_level"):
            if dev.id in self.reservoirs:
                return self.reservoirs[dev.id]
        return None

    def _pump(self, zone_id: str, dev: Device, act: ActuatorSim, on_seconds: float) -> float:
        if dev.id in self.no_flow:
            return 0.0
        volume = dev.raw["flow_ml_per_s"] * on_seconds
        reservoir = self._reservoir_for(zone_id)
        if reservoir is not None:
            volume = min(volume, reservoir["volume_ml"])
            reservoir["volume_ml"] -= volume
        act.delivered_ml += volume
        return volume

    # ------------------------------------------------------------------ sensor reports

    def _sensor_values(self, dev: Device) -> dict[str, float]:
        zones = self.site.zones_of_device(dev.id)
        if not zones:
            return {}
        zone = self.zones[zones[0]]
        values: dict[str, float] = {}
        for role in dev.roles:
            if role == "sensor.air_temp_humidity":
                values["air_temperature"] = zone.air_temperature
                values["relative_humidity"] = zone.relative_humidity
            elif role == "sensor.co2":
                values["co2"] = zone.co2
            elif role == "sensor.soil_moisture" and zone.soil_moisture is not None:
                values["soil_moisture"] = zone.soil_moisture
            elif role == "sensor.light":
                values["illuminance"] = zone.illuminance
            elif role == "sensor.water_level" and dev.id in self.reservoirs:
                r = self.reservoirs[dev.id]
                values["water_level"] = 100.0 * r["volume_ml"] / r["capacity_ml"]
        return values

    def _raw(self, dev: Device, payload: dict) -> float | None:
        """What the part itself measures (volts, centimetres), from the site's calibration, as real firmware reports it."""
        cal = dev.raw.get("calibration", {})
        for quantity, low, high in (("soil_moisture", "dry_v", "wet_v"), ("water_level", "empty_cm", "full_cm")):
            if quantity in payload and low in cal and high in cal:
                return round(cal[low] + (cal[high] - cal[low]) * payload[quantity] / 100.0, 3)
        return None

    def _report(self, now: datetime) -> None:
        self._last_report = now
        for dev in self.site.devices.values():
            if dev.cls != "sensor" or dev.id in self.dropouts or dev.node in self.offline_nodes:
                continue
            payload: dict = {"t": now.isoformat()}
            for quantity, value in self._sensor_values(dev).items():
                noisy = value + self.rng.gauss(0, NOISE.get(quantity, 0.0))
                if quantity not in ("air_temperature", "soil_temperature"):
                    noisy = max(0.0, noisy)
                payload[quantity] = round(self.stuck.get((dev.id, quantity), noisy), 2)
            raw = self._raw(dev, payload)
            if raw is not None:
                payload["raw"] = raw
            if len(payload) > 1:
                self.bus.publish(topics.device(self.site.id, dev.node, dev.id, "state"), payload, retain=True)
