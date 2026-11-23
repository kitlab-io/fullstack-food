"""A smart power strip as a node: one bridge process per strip speaks the MQTT contract
for its outlets, so the hub cannot tell it from an ESP32 node.

The lease is weaker here than on a microcontroller node, and guides must say so: a plug
cannot end an on-command by itself, so it is this bridge that switches the outlet off
when the lease runs out. That covers a hub that died or lost the network. It does not
cover this bridge dying or losing the strip while an outlet is on: the outlet then stays
on until the bridge is back. Run the bridge on the hub host under a supervisor that
restarts it, and keep recipe max_on limits short for anything that heats.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Protocol

from fsf_core import topics
from fsf_core.catalog import Device, Site

MAX_LEASE_S = 3600.0
REFUSED = "actuators accept on (with duration_s) and off"


class PlugError(Exception):
    """The strip could not be reached or refused."""


class PlugBackend(Protocol):
    def set(self, outlet: int, on: bool) -> None: ...
    def is_on(self, outlet: int) -> bool: ...


class MemoryBackend:
    """A strip that exists only in memory, for tests and dry runs."""

    def __init__(self, outlets: int = 6):
        self.on = [False] * outlets
        self.fail = False               # set to make every call raise, as an unreachable strip does
        self.calls: list[tuple[int, bool]] = []

    def set(self, outlet: int, on: bool) -> None:
        if self.fail:
            raise PlugError("strip unreachable")
        self.on[outlet] = on
        self.calls.append((outlet, on))

    def is_on(self, outlet: int) -> bool:
        if self.fail:
            raise PlugError("strip unreachable")
        return self.on[outlet]


class PlugBridge:
    """Drives the outlets of one node. Call tick() about once a second."""

    def __init__(self, site: Site, node_id: str, bus, clock, backend: PlugBackend, refresh_s: float = 60.0):
        if node_id not in site.nodes:
            raise ValueError(f"site {site.id} has no node {node_id!r}")
        self.site, self.node, self.bus, self.clock, self.backend, self.refresh_s = site, node_id, bus, clock, backend, refresh_s
        self.devices: dict[str, Device] = {d.id: d for d in site.devices.values() if d.node == node_id}
        missing = [d.id for d in self.devices.values() if "outlet" not in d.raw]
        if missing:
            raise ValueError(f"devices on {node_id} need an outlet number: {', '.join(missing)}")
        self.lease_until: dict[str, datetime] = {}
        self._reported: dict[str, bool | None] = {}
        self._refreshed: datetime | None = None
        self.reachable = True

    def start(self) -> None:
        for dev in self.devices.values():       # a restart never leaves something running that nobody is leasing
            self._switch(dev, False)
        self.bus.subscribe(f"{topics.ROOT}/{self.site.id}/{self.node}/+/cmd", self._on_cmd)
        self._announce(True)
        self._refresh(self.clock.now(), force=True)

    def stop(self) -> None:
        for dev in self.devices.values():
            self._switch(dev, False)
        self._refresh(self.clock.now(), force=True)
        self._announce(False)

    def _announce(self, online: bool) -> None:
        self.reachable = online
        self.bus.publish(topics.node_status(self.site.id, self.node), "online" if online else "offline", retain=True)

    def _switch(self, dev: Device, on: bool) -> str | None:
        """Returns the error, or None when the strip did it."""
        try:
            self.backend.set(dev.raw["outlet"], on)
            return None
        except PlugError as err:
            return str(err)

    def _publish(self, dev: Device, on: bool, now: datetime) -> None:
        self._reported[dev.id] = on
        self.bus.publish(topics.device(self.site.id, self.node, dev.id, "state"), {"t": now.isoformat(), "on": on}, retain=True)

    def _on_cmd(self, topic: str, payload: bytes) -> None:
        device_id = topic.split("/")[3]
        dev = self.devices.get(device_id)
        if dev is None:
            return
        now = self.clock.now()
        try:
            cmd = json.loads(payload)
            name, duration = cmd.get("name"), cmd.get("duration_s", 0)
        except (ValueError, AttributeError):
            return
        ack = {"id": str(cmd.get("id", "")), "ok": True}
        if name == "on" and isinstance(duration, (int, float)) and duration > 0:
            error = self._switch(dev, True)
            if error is None:
                self.lease_until[dev.id] = now + timedelta(seconds=min(float(duration), MAX_LEASE_S))
                self._publish(dev, True, now)
        elif name == "off":
            self.lease_until.pop(dev.id, None)
            error = self._switch(dev, False)
            if error is None:
                self._publish(dev, False, now)
        else:
            error = REFUSED
        if error:
            ack.update(ok=False, error=error)
        self.bus.publish(topics.device(self.site.id, self.node, dev.id, "ack"), ack)

    def tick(self) -> None:
        now = self.clock.now()
        for device_id, until in list(self.lease_until.items()):
            if now >= until:                    # the lease is over: off, and keep trying if the strip does not answer
                dev = self.devices[device_id]
                if self._switch(dev, False) is None:
                    del self.lease_until[device_id]
                    self._publish(dev, False, now)
        self._refresh(now)

    def _refresh(self, now: datetime, force: bool = False) -> None:
        """Report what the strip itself says, and go offline while it cannot be reached."""
        if not force and self._refreshed is not None and (now - self._refreshed).total_seconds() < self.refresh_s:
            return
        self._refreshed = now
        try:
            actual = {dev.id: self.backend.is_on(dev.raw["outlet"]) for dev in self.devices.values()}
        except PlugError:
            if self.reachable:
                self._announce(False)
            return
        if not self.reachable:
            self._announce(True)
        for dev in self.devices.values():
            if actual[dev.id] and dev.id not in self.lease_until:   # on without a lease (switched by hand, or after a fault)
                if self._switch(dev, False) is None:
                    actual[dev.id] = False
            if force or self._reported.get(dev.id) != actual[dev.id]:
                self._publish(dev, actual[dev.id], now)
