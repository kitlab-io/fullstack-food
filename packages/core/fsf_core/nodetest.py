"""The node contract suite: checks that a node, simulated or real, keeps the MQTT contract.

    fsf node test shelf-node --site sites/local/my-site --mqtt-host hub.local --actuate

Without --actuate only what the node reports by itself is checked. With it, every actuator
on the node is switched on for a few seconds, so use it on a bench or with the zone paused,
and with the hub stopped or the node's zones paused (the hub switches off what it does not
want on, which would fail the lease checks).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Callable

from jsonschema import Draft202012Validator

from . import topics
from .catalog import Catalog, Device, Site, find_repo_root


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""

    def __str__(self) -> str:
        return f"{'PASS' if self.ok else 'FAIL'}  {self.name}" + (f": {self.detail}" if self.detail else "")


class NodeContract:
    """Drives one node over a Bus.

    wait(seconds) must let that much time pass for the node and deliver bus messages:
    sleep-and-poll against a real broker, advance the virtual clock in tests.
    """

    def __init__(self, site: Site, catalog: Catalog, node_id: str, bus, wait: Callable[[float], None],
                 lease_s: float = 3.0, report_within_s: float = 90.0, reply_within_s: float = 5.0):
        if node_id not in site.nodes:
            raise ValueError(f"site {site.id} has no node {node_id!r}")
        self.site, self.catalog, self.node, self.bus, self.wait = site, catalog, node_id, bus, wait
        self.lease_s, self.report_within_s, self.reply_within_s = lease_s, report_within_s, reply_within_s
        self.devices = [d for d in site.devices.values() if d.node == node_id]
        folder = find_repo_root() / "schemas" / "mqtt"
        self._schema = {name: Draft202012Validator(json.loads((folder / f"{name}.schema.json").read_text(encoding="utf-8")))
                        for name in ("state", "ack")}
        self.status: str | None = None
        self.state: dict[str, dict] = {}        # device -> last state payload
        self.acks: dict[str, dict] = {}         # command id -> ack payload
        self.invalid: list[str] = []            # schema violations seen on the way
        bus.subscribe(topics.node_status(site.id, node_id), self._on_status)
        bus.subscribe(f"{topics.ROOT}/{site.id}/{node_id}/+/state", self._on_message)
        bus.subscribe(f"{topics.ROOT}/{site.id}/{node_id}/+/ack", self._on_message)

    # ------------------------------------------------------------------ bus

    def _on_status(self, topic: str, payload: bytes) -> None:
        self.status = payload.decode(errors="replace")

    def _on_message(self, topic: str, payload: bytes) -> None:
        device, leaf = topic.split("/")[3:5]
        try:
            data = json.loads(payload)
        except ValueError:
            self.invalid.append(f"{topic}: not JSON")
            return
        errors = [e.message for e in self._schema[leaf].iter_errors(data)]
        if errors:
            self.invalid.append(f"{topic}: {'; '.join(errors)}")
        if leaf == "state":
            self.state[device] = data
        elif isinstance(data, dict):
            self.acks[str(data.get("id", ""))] = data

    def _until(self, condition: Callable[[], bool], within: float, step: float = 0.5) -> bool:
        waited = 0.0
        while not condition():
            if waited >= within:
                return False
            self.wait(step)
            waited += step
        return True

    def _send(self, dev: Device, command: dict) -> str:
        command_id = uuid.uuid4().hex[:12]
        self.bus.publish(topics.device(self.site.id, self.node, dev.id, "cmd"), {"id": command_id, **command})
        return command_id

    def _acked(self, command_id: str) -> dict | None:
        self._until(lambda: command_id in self.acks, self.reply_within_s)
        return self.acks.get(command_id)

    def _is_on(self, dev: Device) -> bool | None:
        return self.state.get(dev.id, {}).get("on")

    # ------------------------------------------------------------------ checks

    def run(self, actuate: bool = False, power_cut: Callable[[], None] | None = None,
            offline_within_s: float = 60.0) -> list[Check]:
        """power_cut: called when the node should lose power, to check the last will."""
        out: list[Check] = []
        self._until(lambda: self.status is not None, self.reply_within_s)
        out.append(Check("node announces itself as online", self.status == "online", f"status is {self.status!r}"))
        out += self._check_sensors()
        if actuate:
            for dev in self.devices:
                if dev.cls == "actuator":
                    out += self._check_actuator(dev)
                elif "indicator.led_strip" in dev.roles:
                    out += self._check_strip(dev)
        if power_cut is not None:
            power_cut()
            gone = self._until(lambda: self.status == "offline", offline_within_s, step=1.0)
            out.append(Check("last will reports offline when power is lost", gone, f"status is {self.status!r}"))
        out.append(Check("every message matches schemas/mqtt", not self.invalid, "; ".join(self.invalid[:5])))
        return out

    def _check_sensors(self) -> list[Check]:
        components = self.catalog.items["Component"]
        out = []
        for dev in self.devices:
            if dev.cls != "sensor" or not self.site.zones_of_device(dev.id):
                continue
            wanted = [m["quantity"] for role in dev.roles for m in components[role].get("measures", [])]

            def complete(dev=dev, wanted=wanted) -> bool:
                state = self.state.get(dev.id, {})
                return all(isinstance(state.get(q), (int, float)) and not isinstance(state.get(q), bool) for q in wanted)

            ok = self._until(complete, self.report_within_s, step=5.0)
            got = {q: self.state.get(dev.id, {}).get(q) for q in wanted}
            out.append(Check(f"{dev.id} reports {', '.join(wanted)}", ok, "" if ok else f"last state has {got}"))
        return out

    def _check_actuator(self, dev: Device) -> list[Check]:
        out = []
        label = dev.id

        ack = self._acked(self._send(dev, {"name": "on", "duration_s": self.lease_s}))
        on = self._until(lambda: self._is_on(dev) is True, self.reply_within_s) if ack else False
        out.append(Check(f"{label} switches on and acks", bool(ack and ack.get("ok") and on),
                         "no ack" if ack is None else f"ack {ack}, state {self.state.get(dev.id)}"))
        expired = self._until(lambda: self._is_on(dev) is False, self.lease_s + self.reply_within_s)
        out.append(Check(f"{label} switches off by itself when the lease ends", expired, f"state {self.state.get(dev.id)}"))

        self._acked(self._send(dev, {"name": "on", "duration_s": 30}))
        self._until(lambda: self._is_on(dev) is True, self.reply_within_s)
        ack = self._acked(self._send(dev, {"name": "off"}))
        off = self._until(lambda: self._is_on(dev) is False, self.reply_within_s)
        out.append(Check(f"{label} honours off", bool(ack and ack.get("ok") and off),
                         "no ack" if ack is None else f"ack {ack}, state {self.state.get(dev.id)}"))

        ack = self._acked(self._send(dev, {"name": "on"}))
        self.wait(1.0)
        refused = ack is not None and ack.get("ok") is False and self._is_on(dev) is not True
        out.append(Check(f"{label} refuses on without a duration", refused, "no ack" if ack is None else f"ack {ack}"))
        if self._is_on(dev):                    # never leave it running
            self._send(dev, {"name": "off"})

        ack = self._acked(self._send(dev, {"name": "dance"}))
        out.append(Check(f"{label} rejects an unknown command", ack is not None and ack.get("ok") is False,
                         "no ack" if ack is None else f"ack {ack}"))
        return out

    def _check_strip(self, dev: Device) -> list[Check]:
        last = dev.raw.get("led_count", 1) - 1
        pattern = [{"zone": "contract-test", "leds": [0, last], "status": "ok", "color": [0, 40, 0, 0], "effect": "solid"}]
        ack = self._acked(self._send(dev, {"name": "render", "brightness": 0.2, "segments": pattern}))
        shown = self._until(lambda: self.state.get(dev.id, {}).get("segments") == pattern, self.reply_within_s)
        dark = [{**pattern[0], "color": [0, 0, 0, 0], "effect": "off"}]
        self._send(dev, {"name": "render", "brightness": 0.0, "segments": dark})
        return [Check(f"{dev.id} renders and reports what it shows", bool(ack and ack.get("ok") and shown),
                      "no ack" if ack is None else f"ack {ack}")]
