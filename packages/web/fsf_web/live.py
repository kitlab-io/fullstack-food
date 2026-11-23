"""What is true right now, kept from MQTT: zone status, device state, node status, hub state.

Everything here arrives retained, so a freshly started web service is complete as soon as
it has subscribed. Each change is also fanned out to the browsers connected to the event
stream.
"""

from __future__ import annotations

import json
import queue
import threading
import uuid
from collections import deque
from datetime import datetime
from typing import Iterator

from jsonschema import Draft202012Validator

from fsf_core import find_repo_root, topics

KEEPALIVE_S = 15.0
RAW_BUFFER = 2000


def schema_of(parts: list[str]) -> str | None:
    """Which schema in schemas/mqtt/ a topic's payload must match. `parts` is the topic after fsf/<site>/."""
    if parts[0] == "zone":
        return "zone_status" if len(parts) == 3 and parts[2] == "status" else None
    if parts[0] == "hub":
        return {"cmd": "hub_command", "reply": "hub_reply", "state": "hub_state"}.get(parts[1]) if len(parts) == 2 else None
    if parts[0] == "sim":
        return {"cmd": "sim_command", "state": "sim_state"}.get(parts[1]) if len(parts) == 2 else None
    if len(parts) == 2 and parts[1] == "status":
        return "node_status"
    if len(parts) == 3:
        return {"state": "state", "cmd": "command", "ack": "ack"}.get(parts[2])
    return None


class Live:
    def __init__(self, site_id: str, bus, clock):
        self.site_id, self.clock, self.bus = site_id, clock, bus
        self._waiting: dict[str, tuple[threading.Event, list]] = {}     # command id -> (arrived, [reply])
        self._lock = threading.Lock()
        self.zones: dict[str, dict] = {}                        # zone -> status payload
        self.devices: dict[str, dict] = {}                      # device -> {"state": payload, "received": ISO}
        self.nodes: dict[str, dict] = {}                        # node -> {"online": bool, "since": ISO}
        self.hub: dict | None = None
        self.sim: dict | None = None                            # set only when a simulator is on the bus
        self._listeners: list[tuple[queue.Queue, bool]] = []    # (inbox, wants raw MQTT too)
        self._raw: deque[dict] = deque(maxlen=RAW_BUFFER)
        self._seq = 0
        folder = find_repo_root() / "schemas" / "mqtt"
        self._validators = {p.name.split(".")[0]: Draft202012Validator(json.loads(p.read_text(encoding="utf-8")))
                            for p in folder.glob("*.schema.json")}
        bus.subscribe(f"{topics.ROOT}/{site_id}/#", self._on_message)

    def now(self) -> datetime:
        return self.clock.now()

    def _on_message(self, topic: str, payload: bytes) -> None:
        parts = topic.split("/")[2:]
        received = self.now().isoformat() if self.now() else None
        event: dict | None = None
        if parts != ["sim", "clock"]:                           # the simulator's clock ticks are not traffic
            self._send(self._record(topic, parts, payload, received), raw=True)
        try:
            if parts[0] == "zone" and len(parts) == 3 and parts[2] == "status":
                data = json.loads(payload)
                with self._lock:
                    self.zones[parts[1]] = data
                event = {"kind": "zone", "zone": parts[1], "status": data}
            elif parts[0] == "hub" and parts[1:] == ["reply"]:
                reply = json.loads(payload)
                waiter = self._waiting.get(str(reply.get("id")))
                if waiter:
                    waiter[1].append(reply)
                    waiter[0].set()
            elif parts == ["sim", "state"]:
                data = json.loads(payload)
                with self._lock:
                    self.sim = data
                event = {"kind": "sim", "state": data}
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
            self._send(event, raw=False)

    def _record(self, topic: str, parts: list[str], payload: bytes, received: str | None) -> dict:
        """One raw message for the MQTT tail, checked against its schema."""
        text = payload.decode(errors="replace")
        schema, errors, body = schema_of(parts), [], text
        if schema == "node_status":
            errors = [] if text in ("online", "offline") else ["must be online or offline"]
        else:
            try:
                body = json.loads(text)
                if schema:
                    errors = [e.message for e in self._validators[schema].iter_errors(body)][:5]
            except ValueError:
                errors = ["not JSON"] if schema else []
        with self._lock:
            self._seq += 1
            record = {"kind": "mqtt", "n": self._seq, "t": received, "topic": topic, "payload": body,
                      "schema": schema, "errors": errors}
            self._raw.append(record)
        return record

    def _send(self, event: dict, raw: bool) -> None:
        with self._lock:
            listeners = [inbox for inbox, wants_raw in self._listeners if wants_raw or not raw]
        for inbox in listeners:
            try:
                inbox.put_nowait(event)
            except queue.Full:                                  # a browser that stopped reading
                pass

    def command(self, command: dict, timeout: float = 5.0) -> dict | None:
        """Publish an operator command to the hub and wait for its reply. None when the hub does not answer.

        This is the dashboard's only way to change anything: the hub applies its limits and
        interlocks exactly as for automatic control.
        """
        command_id = uuid.uuid4().hex[:12]
        waiter = (threading.Event(), [])
        self._waiting[command_id] = waiter
        try:
            self.bus.publish(topics.hub_cmd(self.site_id), {**command, "id": command_id})
            waiter[0].wait(timeout)
            return waiter[1][0] if waiter[1] else None
        finally:
            del self._waiting[command_id]

    def recent(self, topic: str | None = None, limit: int = 200) -> list[dict]:
        """The newest buffered raw messages, oldest first. `topic` is an MQTT filter with + and #."""
        with self._lock:
            records = list(self._raw)
        if topic:
            records = [r for r in records if topics.matches(topic, r["topic"]) or topic in r["topic"]]
        return records[-limit:]

    def snapshot(self) -> dict:
        with self._lock:
            return {"zones": dict(self.zones), "devices": dict(self.devices), "nodes": dict(self.nodes), "hub": self.hub,
                    "sim": self.sim}

    def stream(self, keepalive: float = KEEPALIVE_S, limit: int | None = None, raw: bool = False) -> Iterator[str]:
        """Server-sent events: one `data:` line per change, a comment line when nothing happens.

        raw: also send every MQTT message (kind "mqtt"), for the live tail.
        """
        inbox: queue.Queue = queue.Queue(maxsize=1000)
        entry = (inbox, raw)
        with self._lock:
            self._listeners.append(entry)
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
                self._listeners.remove(entry)
