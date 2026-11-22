"""What is true right now, kept from MQTT: zone status, device state, node status, hub state.

Everything here arrives retained, so a freshly started web service is complete as soon as
it has subscribed. Each change is also fanned out to the browsers connected to the event
stream.
"""

from __future__ import annotations

import json
import queue
import threading
from datetime import datetime
from typing import Iterator

from fsf_core import topics

KEEPALIVE_S = 15.0


class Live:
    def __init__(self, site_id: str, bus, clock):
        self.site_id, self.clock = site_id, clock
        self._lock = threading.Lock()
        self.zones: dict[str, dict] = {}                        # zone -> status payload
        self.devices: dict[str, dict] = {}                      # device -> {"state": payload, "received": ISO}
        self.nodes: dict[str, dict] = {}                        # node -> {"online": bool, "since": ISO}
        self.hub: dict | None = None
        self._listeners: list[queue.Queue] = []
        bus.subscribe(f"{topics.ROOT}/{site_id}/#", self._on_message)

    def now(self) -> datetime:
        return self.clock.now()

    def _on_message(self, topic: str, payload: bytes) -> None:
        parts = topic.split("/")[2:]
        received = self.now().isoformat() if self.now() else None
        event: dict | None = None
        try:
            if parts[0] == "zone" and len(parts) == 3 and parts[2] == "status":
                data = json.loads(payload)
                with self._lock:
                    self.zones[parts[1]] = data
                event = {"kind": "zone", "zone": parts[1], "status": data}
            elif parts[0] == "hub" and parts[1:] == ["state"]:
                data = json.loads(payload)
                with self._lock:
                    self.hub = data
                event = {"kind": "hub", "state": data}
            elif len(parts) == 2 and parts[1] == "status" and parts[0] not in ("zone", "hub", "sim"):
                online = payload.decode(errors="replace") == "online"
                with self._lock:
                    if self.nodes.get(parts[0], {}).get("online") != online:
                        self.nodes[parts[0]] = {"online": online, "since": received}
                event = {"kind": "node", "node": parts[0], **self.nodes[parts[0]]}
            elif len(parts) == 3 and parts[2] == "state":
                entry = {"state": json.loads(payload), "received": received}
                with self._lock:
                    self.devices[parts[1]] = entry
                event = {"kind": "device", "device": parts[1], **entry}
        except ValueError:
            return                                              # a payload that is not JSON: nothing to show
        if event:
            with self._lock:
                listeners = list(self._listeners)
            for listener in listeners:
                try:
                    listener.put_nowait(event)
                except queue.Full:                              # a browser that stopped reading
                    pass

    def snapshot(self) -> dict:
        with self._lock:
            return {"zones": dict(self.zones), "devices": dict(self.devices), "nodes": dict(self.nodes), "hub": self.hub}

    def stream(self, keepalive: float = KEEPALIVE_S, limit: int | None = None) -> Iterator[str]:
        """Server-sent events: one `data:` line per change, a comment line when nothing happens."""
        inbox: queue.Queue = queue.Queue(maxsize=1000)
        with self._lock:
            self._listeners.append(inbox)
        sent = 0
        try:
            yield "retry: 3000\n\n"
            while limit is None or sent < limit:
                try:
                    event = inbox.get(timeout=keepalive)
                except queue.Empty:
                    yield ": keepalive\n\n"
                    continue
                sent += 1
                yield f"data: {json.dumps(event, separators=(',', ':'))}\n\n"
        finally:
            with self._lock:
                self._listeners.remove(inbox)
