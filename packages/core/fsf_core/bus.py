"""Message bus. The hub and nodes only ever talk through a Bus.

InMemoryBus is deterministic and used by the scenario tests.
MqttBus talks to a real broker and is used by the mock stack and by deployments.
Both deliver messages on the thread that calls publish()/poll(), never concurrently.
"""

from __future__ import annotations

import json
import queue
from collections import deque
from typing import Any, Callable, Protocol

from . import topics

Handler = Callable[[str, bytes], None]


def encode(payload: Any) -> bytes:
    if isinstance(payload, bytes):
        return payload
    if isinstance(payload, str):
        return payload.encode()
    return json.dumps(payload, separators=(",", ":")).encode()


class Bus(Protocol):
    def publish(self, topic: str, payload: Any, retain: bool = False) -> None: ...
    def subscribe(self, pattern: str, handler: Handler) -> None: ...
    def poll(self) -> None: ...


class InMemoryBus:
    def __init__(self) -> None:
        self._subs: list[tuple[str, Handler]] = []
        self._retained: dict[str, bytes] = {}
        self._queue: deque[tuple[str, bytes]] = deque()
        self._draining = False
        self.log: list[tuple[str, bytes]] | None = None  # set to [] to record traffic

    def publish(self, topic: str, payload: Any, retain: bool = False) -> None:
        data = encode(payload)
        if retain:
            self._retained[topic] = data
        if self.log is not None:
            self.log.append((topic, data))
        self._queue.append((topic, data))
        self._drain()

    def subscribe(self, pattern: str, handler: Handler) -> None:
        self._subs.append((pattern, handler))
        for topic, data in list(self._retained.items()):
            if topics.matches(pattern, topic):
                handler(topic, data)

    def unsubscribe_all(self, handlers_of: object) -> None:
        """Drop every subscription whose handler is a bound method of the given object."""
        self._subs = [(p, h) for p, h in self._subs if getattr(h, "__self__", None) is not handlers_of]

    def poll(self) -> None:
        self._drain()

    def _drain(self) -> None:
        if self._draining:
            return
        self._draining = True
        try:
            while self._queue:
                topic, data = self._queue.popleft()
                for pattern, handler in list(self._subs):
                    if topics.matches(pattern, topic):
                        handler(topic, data)
        finally:
            self._draining = False


class MqttBus:
    """Thin wrapper over paho-mqtt. Incoming messages are queued and delivered from poll()."""

    def __init__(self, host: str, port: int = 1883, client_id: str = "", username: str | None = None,
                 password: str | None = None, will: tuple[str, str] | None = None):
        import paho.mqtt.client as mqtt

        self._subs: list[tuple[str, Handler]] = []
        self._inbox: queue.Queue[tuple[str, bytes]] = queue.Queue()
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
        if username:
            self._client.username_pw_set(username, password)
        if will:
            self._client.will_set(will[0], will[1], qos=1, retain=True)
        self._client.on_message = lambda c, u, msg: self._inbox.put((msg.topic, msg.payload))
        self._client.on_connect = self._on_connect
        self._client.connect(host, port)
        self._client.loop_start()

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        for pattern, _ in self._subs:  # resubscribe after a reconnect
            client.subscribe(pattern, qos=1)

    def publish(self, topic: str, payload: Any, retain: bool = False) -> None:
        self._client.publish(topic, encode(payload), qos=1, retain=retain)

    def subscribe(self, pattern: str, handler: Handler) -> None:
        self._subs.append((pattern, handler))
        self._client.subscribe(pattern, qos=1)

    def poll(self) -> None:
        while True:
            try:
                topic, data = self._inbox.get_nowait()
            except queue.Empty:
                return
            for pattern, handler in list(self._subs):
                if topics.matches(pattern, topic):
                    handler(topic, data)

    def close(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()
